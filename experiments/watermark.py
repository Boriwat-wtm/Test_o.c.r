"""ดูว่าลายน้ำแยกออกจากตัวหนังสือจริงด้วยค่าความสว่างได้ไหม

ถ้าแยกได้ นี่คือทางแก้ที่ดีที่สุด เพราะลายน้ำเป็นต้นเหตุของปัญหาหลายอย่างพร้อมกัน
  - Typhoon ติดลูปพ่นข้อความลายน้ำซ้ำ 123 บรรทัด
  - PaddleOCR พ่นบรรทัดเกิน 438 บรรทัด และอ่านครบแค่ 70%
  - เฉลยตัดลายน้ำออก แต่ OCR อ่านเจอ ทำให้เทียบกันไม่เป็นธรรม

แก้ที่ภาพครั้งเดียวได้ประโยชน์กับทุก engine ต่างจากแก้ที่ตัว engine ทีละตัว
"""

from __future__ import annotations

import sys

import numpy as np
from PIL import Image

sys.path.insert(0, "src")

from thai_ocr_bench.config import IMAGE_DIR  # noqa: E402

PAGE = sys.argv[1] if len(sys.argv) > 1 else "doc7a4264_p001"


def main() -> None:
    path = IMAGE_DIR / f"{PAGE}.png"
    with Image.open(path) as raw:
        gray = np.asarray(raw.convert("L"))

    print(f"หน้า {PAGE} — {gray.shape[1]}x{gray.shape[0]} พิกเซล\n")

    total = gray.size
    print("การกระจายค่าความสว่าง (0=ดำ 255=ขาว)")
    edges = [0, 64, 100, 128, 150, 170, 190, 210, 230, 245, 256]
    for lo, hi in zip(edges, edges[1:]):
        n = int(((gray >= lo) & (gray < hi)).sum())
        if n:
            bar = "█" * max(1, round(60 * n / total))
            print(f"  {lo:>3}-{hi - 1:<3} {n / total:>7.3%} {bar}")

    # ตัวหนังสือจริงเป็นสีดำเข้ม ลายน้ำเป็นสีเทาจาง
    # ลองหลายจุดตัดแล้วดูว่าเหลือหมึกกี่เปอร์เซ็นต์
    print("\nลองตัดที่ค่าต่าง ๆ แล้วดูสัดส่วนพิกเซลที่เหลือเป็นหมึก")
    for cut in (100, 128, 150, 170, 190, 200, 210):
        ink = float((gray < cut).mean())
        print(f"  ตัดที่ {cut:>3}  เหลือหมึก {ink:>7.3%}")

    print(
        "\nอ่านผล: ถ้ามีช่วงที่สัดส่วนหมึกคงที่ไม่เปลี่ยนมาก แปลว่ามีสองกลุ่มแยกกันชัด"
        "\n(กลุ่มเข้ม = ตัวหนังสือ กลุ่มจาง = ลายน้ำ) จุดตัดควรอยู่กลางช่วงนั้น"
    )


if __name__ == "__main__":
    main()
