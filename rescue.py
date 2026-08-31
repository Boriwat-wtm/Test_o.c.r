"""ครอปเฉพาะบรรทัดที่น่าสงสัย ขยาย แล้วส่งให้ engine อ่านซ้ำ

รัน:  .venv\\Scripts\\python.exe rescue.py --engine typhoon-api-num+clean
      .venv\\Scripts\\python.exe rescue.py --engine typhoon-2b --samples 3   ดู self-consistency

ยืมแนวคิดมาจาก self-rescue ของ OCR-Agentic-Ai — แทนที่จะซอยทั้งหน้าเป็นตาราง
แล้วอ่านใหม่หมด ให้หาจุดน่าสงสัยก่อน แล้วลงแรงเฉพาะตรงนั้น

ทำไมไม่ซอยทั้งหน้าตามต้นฉบับ
  ๑. VLM เข้าใจ layout ทั้งหน้า ซอยแล้วจุดแข็งนั้นหายไป และมันจะตัดกลางประโยค
  ๒. โควตา API มีจำกัด ซอย ๗x๗ ต่อหน้าคือยิง ๔๙ ครั้งต่อหน้า
     ๑๒ หน้าเป็น ๕๘๘ ครั้ง ราวครึ่งชั่วโมง เทียบกับวิธีนี้ที่ยิงราว ๒๐ ครั้ง

อุปสรรคที่ต้องแก้ก่อน: Typhoon ไม่คืนพิกัดข้อความมาเลย จะครอปก็ไม่รู้ว่าครอปตรงไหน
แก้ด้วยการยืมพิกัดจาก engine ที่คืนมา — บรรทัดเดียวกันย่อมอยู่ที่เดียวกันบนภาพ
(ดู suspect.scan_page)
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from thai_ocr_bench import store
from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR, RESULTS_DIR, ensure_dirs
from thai_ocr_bench.rescue_crop import ZOOM, crop_to_file
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.suspect import (
    Suspect,
    engine_variant,
    independent_peers,
    scan_page,
    thai_digit_by_document,
)
from thai_ocr_bench.render import load_pages
from thai_ocr_bench.thai_text import normalize
from thai_ocr_bench.truth import find_repeating_lines

REPORT_FILE = "rescue.json"


def report_path_for(engine: str) -> Path:
    """แฟ้มผลแยกตาม engine — rescue.json เดิมเก็บได้ทีละตัวเท่านั้น

    รัน engine ที่สองทับตัวแรกแล้วผลตัวแรกหายทันที ซึ่งเจอจริงตอนจะเทียบ
    ความนิ่งของ typhoon-2b กับ typhoon-api ยังเขียน rescue.json ต่อไปด้วย
    เพราะแท็บเดิมอ่านไฟล์นั้นอยู่ ให้หมายถึง "รอบล่าสุด"
    """
    safe = engine.replace("+", "_").replace("/", "_")
    return RESULTS_DIR / f"rescue_{safe}.json"


@dataclass
class Rescued:
    page_id: str
    grid_line: int
    before: str
    after: str
    changed: bool
    box: list[int]
    error: str | None = None
    # เติมเฉพาะตอนใช้ --samples > 1 กับ engine ที่รองรับ read_variants()
    # ค่าเริ่มต้นว่างไว้เพื่อให้ผลเก่าที่ยังไม่มีสองฟิลด์นี้อ่านกลับมาได้
    variants: list[str] = field(default_factory=list)
    agree: bool | None = None


def collect_suspects(results: dict, engine: str) -> list[Suspect]:
    """หาจุดน่าสงสัยของ engine หนึ่งตัวทุกหน้า โดยกรองลายน้ำออกก่อน"""
    per: dict[str, dict[str, tuple[list[str], list]]] = {}
    for name, pages in results.items():
        dropped = find_repeating_lines({p: v.lines for p, v in pages.items()})
        per[name] = {}
        for pid, page in pages.items():
            idx = [i for i, ln in enumerate(page.lines) if ln.strip() not in dropped]
            per[name][pid] = (
                [page.lines[i] for i in idx],
                [page.boxes[i] if i < len(page.boxes) else None for i in idx],
            )

    keep = set(independent_peers(engine, list(per))) | {engine}
    per = {n: v for n, v in per.items() if n in keep}
    # ตัดสินทีละเอกสาร ไม่ใช่รวมทั้งคลัง — คลังมีทั้งเอกสารเลขไทยล้วนและ
    # เอกสารเลขอารบิก รวมกันแล้วตัดสินครั้งเดียวจะผิดสำหรับฝั่งใดฝั่งหนึ่งเสมอ
    thai_doc_of = thai_digit_by_document(
        {pid: lines for pid, (lines, _b) in per[engine].items()}
    )

    # ไม่รวม section_length_outliers ตรงนี้ — จุดที่กฎนั้นจับมักไม่มีกล่อง
    # (ดูเหตุผลใน suspect.section_suspects) ครอปไปอ่านซ้ำไม่ได้อยู่แล้ว
    # จึงกรองทิ้งด้วย `if s.box` ข้างล่างนี้พอดี

    out: list[Suspect] = []
    for pid in sorted(per[engine]):
        page = {n: v[pid] for n, v in per.items() if pid in v}
        out.extend(scan_page(pid, engine, page, thai_doc=thai_doc_of[pid]))
    return [s for s in out if s.box]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="engine ที่จะให้อ่านซ้ำ")
    parser.add_argument("--limit", type=int, help="จำกัดจำนวนจุด (ไว้ลองก่อน)")
    parser.add_argument(
        "--doc",
        action="append",
        help="เจาะเฉพาะเอกสารชื่อนี้ (ใส่ซ้ำได้) — --limit ตัดจากหัวรายการ "
        "ซึ่งเรียงตาม page_id จึงได้แต่เอกสารแรก ๆ เอกสารท้าย ๆ ไม่เคยถูกแตะ",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="อ่านซ้ำกี่รอบแบบสุ่มต่อจุด เพื่อดู self-consistency "
        "(ใช้ได้กับตระกูล typhoon ทั้ง local และ API — ตัวอื่นไม่รองรับ "
        "เพราะควบคุมการสุ่มไม่ได้ · ฝั่ง API กินโควตา N เท่า)",
    )
    args = parser.parse_args()

    ensure_dirs()
    results = store.load()
    if args.engine not in results:
        raise SystemExit(f"ไม่มีผลของ {args.engine} — รัน run_bench.py ก่อน")

    base = args.engine.split("+")[0]
    engine = next((e for e in get_engines() if e.name == base), None)
    if engine is None:
        raise SystemExit(f"ไม่รู้จัก engine {base}")
    ok, why = engine.available()
    if not ok:
        raise SystemExit(f"{base} ยังใช้ไม่ได้: {why}")

    suspects = collect_suspects(results, args.engine)
    if args.doc:
        wanted = set(args.doc)
        by_page = {p.page_id: p.doc_name for p in load_pages()}
        unknown = wanted - set(by_page.values())
        if unknown:
            raise SystemExit(
                "ไม่รู้จักเอกสาร: "
                + ", ".join(sorted(unknown))
                + " · ที่มีให้เลือก: "
                + ", ".join(sorted(set(by_page.values())))
            )
        suspects = [s for s in suspects if by_page.get(s.page_id) in wanted]
        if not suspects:
            print("เอกสารที่เลือกไม่มีจุดน่าสงสัยที่ครอปได้")
            return
    if args.limit:
        suspects = suspects[: args.limit]
    if not suspects:
        print("ไม่พบจุดน่าสงสัยที่มีพิกัดให้ครอป")
        return

    img_dir = CLEAN_IMAGE_DIR if engine_variant(args.engine) == "clean" else IMAGE_DIR
    print(
        f"อ่านซ้ำ {len(suspects)} จุด ด้วย {base} "
        f"(ครอปทีละบรรทัดจาก {img_dir.name}/ แล้วขยาย {ZOOM} เท่า)\n"
    )

    # read_variants() มีเฉพาะตระกูล typhoon (ทั้ง typhoon-2b ในเครื่องและฝั่ง API)
    # ซึ่งควบคุมค่า sampling ตอนสร้างคำตอบได้ engine อื่นอ่านรอบเดียวเสมอ
    # ไม่ว่าเรียกกี่ครั้ง ขอ --samples ไปก็ไม่มีความหมาย
    use_variants = args.samples > 1 and hasattr(engine, "read_variants")
    if args.samples > 1 and not use_variants:
        print(f"หมายเหตุ: {base} ไม่รองรับการอ่านซ้ำแบบสุ่ม ข้าม --samples ไปอ่านรอบเดียว\n")

    out: list[Rescued] = []
    with tempfile.TemporaryDirectory(prefix="rescue_") as tmp:
        for i, s in enumerate(suspects, 1):
            src = img_dir / f"{s.page_id}.png"
            if not src.exists():
                print(f"  {i}/{len(suspects)} ข้าม {s.page_id} — ไม่พบภาพ")
                continue
            piece = Path(tmp) / f"{s.page_id}_{s.grid_line}.png"
            crop_to_file(src, s.box, piece)  # type: ignore[arg-type]

            variants: list[str] = []
            agree: bool | None = None
            if use_variants:
                try:
                    variants = [v for v in engine.read_variants(piece, n=args.samples) if v]
                    after = variants[0] if variants else ""
                    error = None
                except Exception as exc:  # noqa: BLE001 — จุดเดียวพังต้องไม่ทำให้รอบอื่นหยุด
                    after, error = "", f"{type(exc).__name__}: {exc}"
                # เห็นตรงกันทุกรอบ (ไม่นับช่องว่าง) = มั่นใจ ต่างกันแม้รอบเดียว = ไม่มั่นใจ
                agree = len({normalize(v) for v in variants}) <= 1 if variants else None
            else:
                result = engine.run(piece, f"{s.page_id}#{s.grid_line}")
                after = " ".join(ln.text for ln in result.lines).strip()
                error = result.error

            changed = bool(after) and normalize(after) != normalize(s.text)

            out.append(
                Rescued(
                    page_id=s.page_id,
                    grid_line=s.grid_line,
                    before=s.text,
                    after=after,
                    changed=changed,
                    box=list(s.box),  # type: ignore[arg-type]
                    error=error,
                    variants=variants,
                    agree=agree,
                )
            )
            mark = "เปลี่ยน" if changed else "เหมือนเดิม"
            if agree is False:
                mark += " · ไม่มั่นใจ (แต่ละรอบตอบไม่ตรงกัน)"
            print(f"  {i}/{len(suspects)} {s.page_id} บรรทัด {s.grid_line + 1} — {mark}")
            if changed:
                print(f"      เดิม: {s.text[:70]}")
                print(f"      ใหม่: {after[:70]}")
            if agree is False:
                for j, v in enumerate(variants, 1):
                    print(f"      รอบ {j}: {v[:70]}")

    payload = json.dumps(
        {"engine": args.engine, "items": [asdict(r) for r in out]},
        ensure_ascii=False,
        indent=1,
    )
    path = RESULTS_DIR / REPORT_FILE
    path.write_text(payload, encoding="utf-8")
    # เก็บสำเนาแยกตาม engine ไว้ด้วย ไม่งั้นรันตัวถัดไปทับแล้วผลตัวก่อนหายเลย
    report_path_for(args.engine).write_text(payload, encoding="utf-8")
    changed = sum(1 for r in out if r.changed)
    failed = sum(1 for r in out if r.error)
    unstable = sum(1 for r in out if r.agree is False)
    summary = f"\nอ่านซ้ำ {len(out)} จุด · เปลี่ยนไป {changed} · พัง {failed}"
    if use_variants:
        summary += f" · ไม่มั่นใจ {unstable}"
    print(summary)
    print(f"เก็บผลไว้ที่ {path}")
    print("ยังไม่แก้ผลเดิม — ต้องตรวจด้วยตาก่อนว่าอันใหม่ดีกว่าจริง")
    print(
        "อย่าเขียนทับอัตโนมัติ: 'เดิม' เป็นส่วนที่หั่นมาตามกริด ซึ่งบางครั้ง\n"
        "กินยาวกว่าบรรทัดจริงในภาพเล็กน้อย 'ใหม่' ที่สั้นกว่าจึงอาจถูกอยู่แล้ว\n"
        "ส่วนที่หายไปมักไปโผล่ในบรรทัดถัดไปของผลเดิม ไม่ได้หายจริง"
    )


if __name__ == "__main__":
    main()
