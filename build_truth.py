"""ดึงเฉลยจาก text layer แล้วรายงานว่าใช้ได้จริงไหม

นี่คือขั้นที่ต้องผ่านก่อน ถ้า text layer ใช้ไม่ได้ ต้องกลับไปพิมพ์เฉลย 54 หน้าเอง

รัน:  .venv\\Scripts\\python.exe build_truth.py
"""

from __future__ import annotations

import json

from thai_ocr_bench.config import TRUTH_DIR
from thai_ocr_bench.thai_text import THAI_DIGITS, classify_char
from thai_ocr_bench.truth import build_from_sources, truth_defects


def main() -> None:
    pages = build_from_sources()
    if not pages:
        print("ไม่มีไฟล์ไหนมี text layer เลย ต้องพิมพ์เฉลยเองทั้งหมด")
        return

    total_chars = sum(len(p.text) for p in pages.values())
    print(f"ดึงเฉลยจาก text layer ได้ {len(pages)} หน้า · {total_chars:,} ตัวอักษร\n")

    counts: dict[str, int] = {}
    for page in pages.values():
        for ch in page.text:
            cls = classify_char(ch)
            counts[cls] = counts.get(cls, 0) + 1

    print("สัดส่วนอักขระในเฉลย")
    for cls, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {cls:<18} {n:>8,}  {n / total_chars:>6.1%}")

    thai_digits = sum(page.text.count(d) for page in pages.values() for d in THAI_DIGITS)
    print(f"\nเลขไทยในเฉลย: {thai_digits:,} ตัว")

    for report in sorted(TRUTH_DIR.glob("*_dropped.json")):
        dropped = json.loads(report.read_text(encoding="utf-8"))
        if not dropped:
            continue
        print(f"\nบรรทัดที่กรองออก (สงสัยเป็นลายน้ำ/หัวท้ายกระดาษ) — {report.stem}")
        for line in dropped[:12]:
            print(f"  · {line[:90]}")

    # ตรวจเฉลยเองก่อนเอาไปใช้ — เจอเฉลยเสียมาสองรอบแล้วทั้งคู่โดยบังเอิญ
    # ทุกตัวเลขในโปรเจกต์เชื่อถือได้เท่ากับเฉลยเท่านั้น
    defects = [(pid, d) for pid, page in pages.items() for d in truth_defects(page.lines)]
    if defects:
        print(f"\n⚠ เฉลยมีจุดที่น่าจะเสีย {len(defects)} จุด — ต้องดูด้วยตาแล้วแก้เอง")
        print("  (ตั้งใจไม่ซ่อมอัตโนมัติ เพราะเดาว่าต้นฉบับควรเป็นอะไร"
              " คือสร้างเฉลยผิดชนิดใหม่)")
        for pid, (line_no, label, snippet) in defects[:10]:
            print(f"  · {pid} บรรทัด {line_no + 1} — {label}")
            print(f"      {snippet!r}")
        if len(defects) > 10:
            print(f"  · ...อีก {len(defects) - 10} จุด")
    else:
        print("\nตรวจเฉลยแล้วไม่พบจุดที่น่าจะเสีย")

    print("\nตัวอย่างเฉลย 3 หน้าแรก")
    for page_id, page in list(pages.items())[:3]:
        print(f"\n--- {page_id} ({len(page.lines)} บรรทัด) ---")
        for line in page.lines[:6]:
            print(f"  {line[:88]}")


if __name__ == "__main__":
    main()
