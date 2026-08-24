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

from PIL import Image

from thai_ocr_bench import store
from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR, RESULTS_DIR, ensure_dirs
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.suspect import (
    Suspect,
    engine_variant,
    independent_peers,
    scan_page,
    thai_digit_document,
)
from thai_ocr_bench.thai_text import normalize
from thai_ocr_bench.truth import find_repeating_lines

REPORT_FILE = "rescue.json"

# ครอปชิดตัวอักษรเกินไปจะตัดวรรณยุกต์บนกับสระล่างทิ้ง ซึ่งเป็นตัวที่ต้องอ่านที่สุด
PAD_Y = 16
# แนวนอนเผื่อเยอะกว่ามาก เพราะกล่องที่ยืมมามักจบก่อนตัวอักษรตัวสุดท้ายของบรรทัด
# ๒๐๐ px ที่ ๓๐๐ DPI ราวสองเซนติเมตร พอครอบส่วนที่ engine ตีกรอบพลาด
PAD_X = 200
# ขยายให้ตัวหนังสือใหญ่ขึ้น เป็นหัวใจของ self-rescue — บรรทัดที่ย่อรวมมากับทั้งหน้า
# จะมีความละเอียดต่อตัวอักษรต่ำกว่าตอนส่งไปเดี่ยว ๆ มาก
ZOOM = 4
# ไม่ให้ภาพครอปใหญ่เกินจำเป็น เปลืองโทเคนเปล่า ๆ
MAX_WIDTH = 3000


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
    # ค่าเริ่มต้นว่างไว้เพื่อให้ผลเก่าที่ยังไม่มีสองฟิลด์นี้อ่านกลับมาได้ (asdict ฝั่งเขียน
    # ใส่มาเสมอ แต่โครงนี้กันไว้เผื่อมีโค้ดอื่นสร้าง Rescued ตรง ๆ โดยไม่ผ่าน main())
    variants: list[str] = field(default_factory=list)
    agree: bool | None = None


def crop_line(image_path: Path, box: tuple[int, int, int, int], out: Path) -> None:
    """ตัดบรรทัดเดียวออกมาแล้วขยาย เก็บเป็นไฟล์ให้ engine อ่าน

    เผื่อขอบแนวนอนมากกว่าแนวตั้ง เพราะกล่องที่ยืมมาพลาดคนละแบบในสองแกน
    ตำแหน่งแนวตั้งของบรรทัดแม่นกว่าขอบเขตแนวนอนมาก

    เคยลองครอปเต็มความกว้างหน้าเทียบด้วย ผลออกมาเท่ากันทุกตัวเลข
    จึงเลือกครอปตามกล่องเพราะภาพเล็กกว่า ประหยัดโทเคน
    """
    with Image.open(image_path) as im:
        x, y, w, h = box
        area = (
            max(0, x - PAD_X),
            max(0, y - PAD_Y),
            min(im.width, x + w + PAD_X),
            min(im.height, y + h + PAD_Y),
        )
        piece = im.crop(area).convert("RGB")
    scale = min(ZOOM, MAX_WIDTH / max(piece.width, 1))
    if scale > 1:
        piece = piece.resize(
            (int(piece.width * scale), int(piece.height * scale)), Image.LANCZOS
        )
    piece.save(out)


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
    thai_doc = thai_digit_document(
        [ln for lines, _ in per[engine].values() for ln in lines]
    )

    # ไม่รวม section_length_outliers ตรงนี้ — จุดที่กฎนั้นจับมักไม่มีกล่อง
    # (ดูเหตุผลใน suspect.section_suspects) ครอปไปอ่านซ้ำไม่ได้อยู่แล้ว
    # จึงกรองทิ้งด้วย `if s.box` ข้างล่างนี้พอดี

    out: list[Suspect] = []
    for pid in sorted(per[engine]):
        page = {n: v[pid] for n, v in per.items() if pid in v}
        out.extend(scan_page(pid, engine, page, thai_doc=thai_doc))
    return [s for s in out if s.box]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="engine ที่จะให้อ่านซ้ำ")
    parser.add_argument("--limit", type=int, help="จำกัดจำนวนจุด (ไว้ลองก่อน)")
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="อ่านซ้ำกี่รอบแบบสุ่มต่อจุด เพื่อดู self-consistency "
        "(ใช้ได้เฉพาะ engine ที่มี read_variants() เช่น typhoon-2b — "
        "ตัวอื่นไม่รองรับเพราะควบคุมการสุ่มไม่ได้)",
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
    if args.limit:
        suspects = suspects[: args.limit]
    if not suspects:
        print("ไม่พบจุดน่าสงสัยที่มีพิกัดให้ครอป")
        return

    img_dir = CLEAN_IMAGE_DIR if engine_variant(args.engine) == "clean" else IMAGE_DIR
    print(f"อ่านซ้ำ {len(suspects)} จุด ด้วย {base} (ภาพจาก {img_dir.name}/)\n")

    # read_variants() มีเฉพาะ engine ที่ควบคุมการสุ่มได้ (typhoon-2b ที่รันในเครื่อง)
    # engine อื่นอ่านรอบเดียวเสมอไม่ว่าเรียกกี่ครั้ง ขอ --samples ไปก็ไม่มีความหมาย
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
            crop_line(src, s.box, piece)  # type: ignore[arg-type]

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

    path = RESULTS_DIR / REPORT_FILE
    path.write_text(
        json.dumps(
            {"engine": args.engine, "items": [asdict(r) for r in out]},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
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
