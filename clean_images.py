"""ลบลายน้ำออกจากภาพทุกหน้า เก็บไว้ที่ data/cleaned/

ทำไมต้องมีขั้นนี้: ลายน้ำเป็นต้นเหตุร่วมของปัญหาหลายอย่าง
  - Typhoon ติดลูปพ่นข้อความลายน้ำซ้ำ 123 บรรทัดจนชนเพดาน token (320 วินาที/หน้า)
  - PaddleOCR พ่นบรรทัดเกิน 438 บรรทัด และอ่านครบแค่ 70%
  - เฉลยกรองลายน้ำออกแล้ว แต่ OCR อ่านเจอ การเทียบจึงไม่เป็นธรรม

แก้ที่ภาพครั้งเดียวได้ผลกับทุก engine

รัน:  .venv\\Scripts\\python.exe clean_images.py
      .venv\\Scripts\\python.exe clean_images.py --always   บังคับลบทุกหน้า
"""

from __future__ import annotations

import argparse

from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR, ensure_dirs
from thai_ocr_bench.preprocess import DEFAULT_THRESHOLD, clean_file
from thai_ocr_bench.render import load_pages


def main() -> None:
    parser = argparse.ArgumentParser(description="ลบลายน้ำออกจากภาพ")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--always", action="store_true", help="ลบทุกหน้าแม้ตรวจไม่พบลายน้ำ"
    )
    args = parser.parse_args()

    ensure_dirs()
    pages = load_pages()
    if not pages:
        print("ยังไม่มีภาพ รัน render_pages.py ก่อน")
        return

    stats: dict[str, list] = {}
    for page in pages:
        src = IMAGE_DIR / f"{page.page_id}.png"
        if not src.exists():
            continue
        before, after, did = clean_file(
            src,
            CLEAN_IMAGE_DIR / f"{page.page_id}.png",
            args.threshold,
            always=args.always,
        )
        row = stats.setdefault(page.doc_name, [0, 0, []])
        row[0 if did else 1] += 1
        row[2].append(before)

    header = f"{'เอกสาร':<26}{'ลบลายน้ำ':>11}{'ข้าม':>7}{'ชั้นจางเฉลี่ย':>16}"
    print(f"\nจุดตัดที่ใช้: {args.threshold}\n")
    print(header)
    print("-" * 62)
    cleaned = skipped = 0
    for name, (did, skip, values) in stats.items():
        avg = sum(values) / len(values) if values else 0
        print(f"{name:<26}{did:>11}{skip:>7}{avg:>15.2%}")
        cleaned += did
        skipped += skip
    print("-" * 62)
    print(f"ลบ {cleaned} หน้า · ข้าม {skipped} หน้า → {CLEAN_IMAGE_DIR}")
    print("\nรันเทียบกับชุดดิบ:  run_bench.py --clean")


if __name__ == "__main__":
    main()
