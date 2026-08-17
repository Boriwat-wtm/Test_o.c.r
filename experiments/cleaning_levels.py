"""เทียบข้อความ 3 ระดับ เพื่อให้เห็นว่า "ทำความสะอาด" แต่ละขั้นทำอะไร

ระดับ 1  ดิบจริง       ต่อชิ้นจาก image_to_data ด้วยช่องว่าง (วิธีเดิมที่เป็นบั๊ก)
ระดับ 2  หลังแก้ engine ข้อความจาก image_to_string — นี่คือสิ่งที่ Tesseract อ่านได้จริง
ระดับ 3  หลัง normalize รูปที่เอาไปเทียบกับเฉลยตอนคิดคะแนน

ข้อสำคัญ: normalize ตัดแค่ "สิ่งที่ไม่ใช่ความผิด" เช่น ช่องว่างกับลำดับสระ
มันไม่ได้ซ่อนความผิดจริง ที→ที่ ยังนับผิดอยู่ ดูได้จากคอลัมน์ CER
"""

from __future__ import annotations

import os
import sys

import pytesseract
from PIL import Image

sys.path.insert(0, "src")

from thai_ocr_bench.config import IMAGE_DIR, TESSDATA_DIR, TESSERACT_EXE  # noqa: E402
from thai_ocr_bench.metrics import compare  # noqa: E402
from thai_ocr_bench.thai_text import normalize  # noqa: E402
from thai_ocr_bench.truth import load as load_truth  # noqa: E402

PAGE = sys.argv[1] if len(sys.argv) > 1 else "doc7a4264_p001"
CONFIG = "--oem 1 --psm 6"


def main() -> None:
    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

    image_path = IMAGE_DIR / f"{PAGE}.png"
    with Image.open(image_path) as image:
        raw_string = pytesseract.image_to_string(image, lang="tha+eng", config=CONFIG)
        data = pytesseract.image_to_data(
            image, lang="tha+eng", config=CONFIG, output_type=pytesseract.Output.DICT
        )

    # ระดับ 1 — วิธีเดิม: จับกลุ่มตามบรรทัดแล้วต่อด้วยช่องว่าง
    grouped: dict[tuple, list[int]] = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(i)
    level1 = [" ".join(data["text"][i] for i in idx) for idx in grouped.values()]

    # ระดับ 2 — วิธีที่แก้แล้ว
    level2 = [ln.strip() for ln in raw_string.splitlines() if ln.strip()]

    truth = load_truth().get(PAGE)
    truth_lines = truth.lines if truth else []

    print(f"หน้า {PAGE}\n")
    print(f"{'':4}{'ระดับ':<26}{'ตัวอย่างบรรทัดที่ 3':<64}")
    print("=" * 96)

    for idx in (2, 5, 6):
        if idx >= len(level2):
            continue
        print(f"  บรรทัดที่ {idx + 1}")
        samples = [
            ("1. ดิบ (ต่อด้วยช่องว่าง)", level1[idx] if len(level1) > idx else ""),
            ("2. หลังแก้ engine", level2[idx]),
            ("3. หลัง normalize", normalize(level2[idx])),
        ]
        for label, text in samples:
            print(f"    {label:<26}{text[:62]}")
        print()

    if not truth_lines:
        print("\n(ยังไม่มีเฉลยของหน้านี้ จึงคิด CER ไม่ได้)")
        return

    print("\n" + "=" * 96)
    print("CER ของทั้งหน้า เทียบกับเฉลยเดียวกัน")
    print("=" * 96)
    truth_text = "\n".join(truth_lines)

    for label, lines in (
        ("1. ดิบ (ต่อด้วยช่องว่าง)", level1),
        ("2. หลังแก้ engine", level2),
    ):
        pred = "\n".join(lines)
        with_norm = compare(truth_text, pred)
        keep_spaces = compare(truth_text, pred, keep_spaces=True)
        print(
            f"  {label:<28} เทียบแบบเก็บช่องว่าง {keep_spaces.cer:>7.1%}   "
            f"เทียบแบบ normalize {with_norm.cer:>7.1%}"
        )

    print(
        "\nอ่านตาราง: normalize ทำให้ระดับ 1 กับ 2 ได้คะแนนใกล้กัน เพราะช่องว่างขยะ"
        "\nไม่ใช่ความผิดจริง ส่วนตัวเลขที่ยังเหลือคือความผิดของ Tesseract จริง ๆ"
    )


if __name__ == "__main__":
    main()
