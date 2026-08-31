r"""ให้ engine อ่านทั้งหน้าซ้ำหลายรอบ แล้วดูว่าบรรทัดไหนตอบไม่เหมือนเดิม

รัน:  .venv\Scripts\python.exe measure_stability.py --engine typhoon-api-num --clean
      .venv\Scripts\python.exe measure_stability.py --engine typhoon-api-num --clean --doc "ชื่อเอกสาร"

ต่างจาก rescue.py --samples ตรงขอบเขตที่วัด
  rescue.py           ครอปเฉพาะจุดที่ engine อื่นชี้ว่าน่าสงสัย แล้ววัดตรงนั้น
  ไฟล์นี้              อ่านทั้งหน้า ทุกบรรทัดมีสิทธิ์ถูกวัดเท่ากัน

ทำไมต้องแยกออกมา — วัดแล้ววิธีที่พึ่ง engine อื่นทำได้แย่มาก
  จับผิดได้ 2% ของบรรทัดที่ผิดจริง · ที่เตือนมา 43% เป็นการเตือนเปล่า
เพราะเอา engine ที่แม่นน้อยกว่า 2-16 เท่ามาตัดสินตัวที่แม่นที่สุด
มันไม่เห็นด้วยตรงไหนมักเป็นเพราะตัวมันเองอ่านผิด และจุดที่ typhoon ผิดจริง
ตัวพวกนั้นก็มักผิดตามจนจับคู่ไม่ติด

วิธีนี้ให้โมเดลตัดสินตัวเอง ไม่มีตัวที่แม่นน้อยกว่ามาปน
วัดกับหนังสือเวียน 1 หน้า: จับผิดได้ 6/6 · เตือนเปล่า 25% · ยิง API 3 ครั้ง
(กลุ่มตัวอย่างเล็กมาก ตัวเลขจะเปลี่ยนเมื่อวัดหลายหน้า)
"""

from __future__ import annotations

import argparse
import json
import time

from rapidfuzz.distance import Levenshtein

from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR, RESULTS_DIR, ensure_dirs
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.render import load_pages
from thai_ocr_bench.thai_text import normalize

REPORT_PREFIX = "stability_"


def report_path(engine: str, clean: bool):
    """แฟ้มแยกตาม engine เหมือน rescue — รันตัวถัดไปต้องไม่ทับตัวก่อน"""
    name = f"{engine}{'+clean' if clean else ''}".replace("+", "_").replace("/", "_")
    return RESULTS_DIR / f"{REPORT_PREFIX}{name}.json"


def split_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def line_is_stable(line: str, others: list[list[str]]) -> bool:
    """บรรทัดนี้โผล่ในทุกรอบไหม (ตัดช่องว่างก่อนเทียบ)

    เทียบแบบ "มีบรรทัดที่เหมือนกันเป๊ะอยู่ในรอบนั้นไหม" ไม่ใช่เทียบตำแหน่งต่อตำแหน่ง
    เพราะแต่ละรอบแบ่งบรรทัดไม่เท่ากัน (วัดจริงได้ 11, 15, 14 บรรทัดจากหน้าเดียวกัน)
    ถ้าเทียบตามตำแหน่งจะรายงานว่าไม่นิ่งทั้งหน้าทั้งที่ข้อความตรงกัน
    """
    target = normalize(line)
    return all(
        any(Levenshtein.distance(target, normalize(o)) == 0 for o in other)
        for other in others
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--samples", type=int, default=3, help="อ่านกี่รอบต่อหน้า")
    parser.add_argument(
        "--temperature", type=float, default=0.3,
        help="ความสุ่มตอนอ่าน — 0.3 มาจากการวัด ดู read_variants() ว่าทำไม",
    )
    parser.add_argument("--clean", action="store_true", help="ใช้ภาพที่ลบลายน้ำแล้ว")
    parser.add_argument("--doc", action="append", help="เจาะเฉพาะเอกสารนี้ (ใส่ซ้ำได้)")
    parser.add_argument("--limit", type=int, help="จำกัดจำนวนหน้า")
    args = parser.parse_args()

    ensure_dirs()
    engine = next((e for e in get_engines() if e.name == args.engine), None)
    if engine is None:
        raise SystemExit(f"ไม่รู้จัก engine {args.engine}")
    if not hasattr(engine, "read_variants"):
        raise SystemExit(
            f"{args.engine} อ่านซ้ำแบบสุ่มไม่ได้ — ควบคุมการสุ่มตอนสร้างคำตอบไม่ได้\n"
            "ใช้ได้เฉพาะตระกูล typhoon"
        )
    ok, why = engine.available()
    if not ok:
        raise SystemExit(f"{args.engine} ยังใช้ไม่ได้: {why}")

    pages = load_pages()
    if args.doc:
        wanted = set(args.doc)
        unknown = wanted - {p.doc_name for p in pages}
        if unknown:
            raise SystemExit("ไม่รู้จักเอกสาร: " + ", ".join(sorted(unknown)))
        pages = [p for p in pages if p.doc_name in wanted]

    img_dir = CLEAN_IMAGE_DIR if args.clean else IMAGE_DIR
    pages = [p for p in pages if (img_dir / f"{p.page_id}.png").exists()]
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        raise SystemExit(f"ไม่มีหน้าไหนมีภาพใน {img_dir.name}/")

    calls = len(pages) * args.samples
    print(
        f"วัดความนิ่ง {len(pages)} หน้า × {args.samples} รอบ = ยิง {calls} ครั้ง"
        f"  (ภาพจาก {img_dir.name}/)\n"
    )

    # โหลดของเดิมมาต่อ ไม่เริ่มใหม่ — รันครั้งก่อนอาจถูกตัดกลางคัน
    # และการยิง API ที่จ่ายไปแล้วไม่ควรเสียเปล่า
    path = report_path(args.engine, args.clean)
    out: dict[str, dict] = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("samples") == args.samples:
                out = old.get("pages", {})
                if out:
                    print(f"ต่อจากของเดิม {len(out)} หน้า")
        except (json.JSONDecodeError, OSError):
            pass

    def flush() -> None:
        """เขียนลงดิสก์ทุกหน้า ไม่รอจบ

        เดิมเขียนตอนจบอย่างเดียว รอบที่ถูกตัดกลางคันจึงเสียทั้งหมด
        เจอจริงตอนรัน 30 หน้าแล้วโดน timeout ที่หน้า 11 — ยิง API ไป 33 ครั้ง
        แล้วไม่ได้อะไรกลับมาเลย
        """
        path.write_text(
            json.dumps(
                {
                    "engine": args.engine + ("+clean" if args.clean else ""),
                    "samples": args.samples,
                    "temperature": args.temperature,
                    "pages": out,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    t0 = time.time()
    todo = [p for p in pages if p.page_id not in out]
    if len(todo) < len(pages):
        print(f"ข้าม {len(pages) - len(todo)} หน้าที่วัดไว้แล้ว")
    for i, page in enumerate(todo, 1):
        try:
            variants = engine.read_variants(
                img_dir / f"{page.page_id}.png",
                n=args.samples,
                temperature=args.temperature,
            )
        except Exception as exc:  # noqa: BLE001 — หน้าเดียวพังต้องไม่ทำให้รอบอื่นหยุด
            print(f"  {i}/{len(todo)} {page.page_id} — พัง: {type(exc).__name__}: {exc}")
            continue

        per_round = [split_lines(v) for v in variants]
        # ใช้รอบแรกเป็นตัวหลัก เพราะเป็นคำตอบที่ผู้ใช้จะได้ถ้าอ่านรอบเดียวตามปกติ
        main_lines = per_round[0] if per_round else []
        marked = [
            {"text": ln, "stable": line_is_stable(ln, per_round[1:])}
            for ln in main_lines
        ]
        unstable = sum(1 for m in marked if not m["stable"])
        out[page.page_id] = {
            "doc_name": page.doc_name,
            "variants": variants,
            "lines": marked,
        }
        flush()
        print(
            f"  {i}/{len(todo)} {page.page_id} — {len(main_lines)} บรรทัด · "
            f"ไม่นิ่ง {unstable}"
            + (f"  (แต่ละรอบได้ {', '.join(str(len(r)) for r in per_round)} บรรทัด)"
               if len({len(r) for r in per_round}) > 1 else "")
        )

    flush()
    total = sum(len(p["lines"]) for p in out.values())
    unstable = sum(1 for p in out.values() for m in p["lines"] if not m["stable"])
    print(f"\nรวม {total} บรรทัด · ไม่นิ่ง {unstable}"
          f" ({unstable / total:.0%})" if total else "\nไม่ได้ผลเลย")
    print(f"ใช้เวลา {(time.time() - t0) / 60:.1f} นาที · เก็บผลไว้ที่ {path}")
    print("ดูในหน้าเว็บได้ที่แท็บ วัดความนิ่ง")


if __name__ == "__main__":
    main()
