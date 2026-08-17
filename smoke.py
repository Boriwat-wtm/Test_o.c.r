"""ทดสอบเร็ว ๆ ว่า engine อ่านหน้าหนึ่งออกมาได้จริงไหม ก่อนรันเต็ม

รัน:  .venv\\Scripts\\python.exe smoke.py doc8103e5_p002
"""

from __future__ import annotations

import sys

from thai_ocr_bench.config import IMAGE_DIR
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.render import load_pages
from thai_ocr_bench.thai_text import THAI_DIGITS


def main() -> None:
    page_id = sys.argv[1] if len(sys.argv) > 1 else None
    pages = load_pages()
    if not pages:
        print("ยังไม่มีภาพ รัน render_pages.py ก่อน")
        return

    page = next((p for p in pages if p.page_id == page_id), pages[0])
    image = IMAGE_DIR / f"{page.page_id}.png"
    print(f"หน้า {page.page_id} — {page.doc_name} หน้า {page.page_no}\n")

    for engine in get_engines():
        ready, reason = engine.available()
        if not ready:
            print(f"[{engine.name}] ยังไม่พร้อม: {reason}\n")
            continue

        result = engine.run(image, page.page_id)
        if not result.ok:
            print(f"[{engine.name}] พัง: {result.error}\n")
            continue

        text = result.text
        thai_digits = sum(text.count(d) for d in THAI_DIGITS)
        print(
            f"[{engine.name}] {len(result.lines)} บรรทัด · {len(text)} ตัวอักษร · "
            f"เลขไทย {thai_digits} ตัว · {result.elapsed_ms:.0f} ms"
        )
        print("-" * 70)
        for line in result.lines[:14]:
            conf = f"{line.confidence:.0%}" if line.confidence is not None else "  - "
            print(f"  {conf:>5}  {line.text}")
        if len(result.lines) > 14:
            print(f"  ... อีก {len(result.lines) - 14} บรรทัด")
        print()


if __name__ == "__main__":
    main()
