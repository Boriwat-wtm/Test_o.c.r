"""ตรวจว่า text layer ที่ดึงออกมาเชื่อถือได้แค่ไหน

ตรวจสองเรื่องที่พบว่าน่าสงสัยจากการดูด้วยตา
  1. สระอา (า) ถูกดึงออกมาเป็น สระอำ (ำ) หรือไม่
  2. มีตัวอักษรหายไปกลางบรรทัดหรือไม่
"""

from __future__ import annotations

import pymupdf

from thai_ocr_bench.config import SOURCE_DIR

PDF = SOURCE_DIR / "กฏหมายที่ดินมีลายน้ำ.pdf"
SARA_AA, SARA_AM = "า", "ำ"


def main() -> None:
    with pymupdf.open(PDF) as doc:
        page = doc[2]  # หน้า 3
        modes = {
            "text": page.get_text("text"),
            "text sort": page.get_text("text", sort=True),
            "blocks": "\n".join(b[4] for b in page.get_text("blocks")),
        }

    for name, content in modes.items():
        aa = content.count(SARA_AA)
        am = content.count(SARA_AM)
        space_am = content.count(" " + SARA_AM)
        print(
            f"{name:<12} ตัวอักษร {len(content):>6,}  "
            f"า={aa:<5} ำ={am:<5} ' ำ'={space_am:<5}"
        )

    print("\n--- ข้อความดิบ 6 บรรทัดแรก (โหมด text) ---")
    for line in modes["text"].splitlines()[:6]:
        print(f"  {line[:100]}")

    print("\n--- ทดลองซ่อม ---")
    sample = modes["text"].splitlines()[2] if len(modes["text"].splitlines()) > 2 else ""
    print(f"  ก่อน: {sample[:100]}")
    print(f"  หลัง: {repair(sample)[:100]}")


def repair(text: str) -> str:
    """ซ่อมการแมปสระที่ผิดจาก PDF ที่สร้างด้วย Word + THSarabunPSK

    รูปแบบที่พบ
      ' ำ'  (ช่องว่าง + สระอำ)  = สระอำ ตัวจริง
      'ำ'   (เดี่ยว ๆ)          = สระอา ที่ถูกแมปผิด

    ต้องแทนที่ตัวจริงก่อน แล้วค่อยแปลงตัวที่เหลือ ไม่งั้นจะเพี้ยนทั้งคู่
    """
    placeholder = ""
    text = text.replace(" " + SARA_AM, placeholder)
    text = text.replace(SARA_AM, SARA_AA)
    return text.replace(placeholder, SARA_AM)


if __name__ == "__main__":
    main()
