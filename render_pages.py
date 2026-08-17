"""แปลง PDF ทุกไฟล์ในโฟลเดอร์ต้นทางเป็นภาพ PNG แล้วรายงานสิ่งที่ต้องตรวจ

รัน:  .venv\\Scripts\\python.exe render_pages.py
      .venv\\Scripts\\python.exe render_pages.py --force   (แปลงใหม่ทุกหน้า)
"""

from __future__ import annotations

import argparse
import time

from thai_ocr_bench.render import render_all


def main() -> None:
    parser = argparse.ArgumentParser(description="แปลง PDF เป็นภาพสำหรับ OCR")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--force", action="store_true", help="แปลงใหม่แม้มีไฟล์อยู่แล้ว")
    args = parser.parse_args()

    started = time.time()
    pages = render_all(dpi=args.dpi, force=args.force)
    elapsed = time.time() - started

    print(f"\nrender เสร็จ {len(pages)} หน้า ใน {elapsed:.1f} วินาที (DPI {args.dpi})\n")

    by_doc: dict[str, list] = {}
    for page in pages:
        by_doc.setdefault(page.doc_name, []).append(page)

    header = f"{'เอกสาร':<30}{'หน้า':>6}{'rotate':>8}{'ขนาดภาพ':>14}{'แนว':>9}{'text layer':>12}"
    print(header)
    print("-" * len(header))

    for name, group in by_doc.items():
        first = group[0]
        orientation = "ตั้ง" if first.portrait else "ตะแคง!"
        chars = sum(p.text_chars for p in group)
        text_layer = f"{chars:,} ตัว" if first.has_text_layer else "ไม่มี"
        size = f"{first.width}x{first.height}"
        print(
            f"{name:<30}{len(group):>6}{first.rotation:>8}{size:>14}"
            f"{orientation:>9}{text_layer:>12}"
        )

    print("-" * len(header))

    sideways = [p for p in pages if not p.portrait]
    if sideways:
        print(f"\n!! มี {len(sideways)} หน้าที่ยังตะแคง ต้องแก้ก่อนวัดผล:")
        for p in sideways[:10]:
            print(f"   {p.page_id}  {p.doc_name} หน้า {p.page_no}")
    else:
        print("\nทุกหน้าตั้งตรง")

    with_text = [p for p in pages if p.has_text_layer]
    print(
        f"หน้าที่มี text layer ใช้เป็นเฉลยอัตโนมัติได้: {len(with_text)} / {len(pages)}"
    )


if __name__ == "__main__":
    main()
