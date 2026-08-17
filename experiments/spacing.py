"""หาว่าทำไม Tesseract ให้ข้อความไทยแบบ 'ม ิ ต ิ ด ้ า น' และแก้ได้ไหม

สมมติฐาน
  A. Tesseract ตัดคำไทยที่ระดับ cluster แล้วเราเอามาต่อด้วยช่องว่างเอง (บั๊กของเรา)
  B. Tesseract ใส่ช่องว่างมาเองตั้งแต่ต้น (บั๊กของ Tesseract)

ถ้าเป็น A แก้ได้ด้วยการดูระยะห่างระหว่างกรอบคำ แล้วค่อยตัดสินว่าจะใส่ช่องว่างไหม
"""

from __future__ import annotations

import os
import sys

import pytesseract
from PIL import Image

sys.path.insert(0, "src")

from thai_ocr_bench.config import IMAGE_DIR, TESSDATA_DIR, TESSERACT_EXE  # noqa: E402

PAGE = sys.argv[1] if len(sys.argv) > 1 else "doc8103e5_p002"
LINE_INDEX = 0


def setup() -> None:
    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)


def group_lines(data: dict) -> list[list[int]]:
    grouped: dict[tuple, list[int]] = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (
            data["page_num"][i],
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i],
        )
        grouped.setdefault(key, []).append(i)
    return list(grouped.values())


def join_naive(data: dict, idx: list[int]) -> str:
    """วิธีเดิม — ต่อทุกชิ้นด้วยช่องว่าง"""
    return " ".join(data["text"][i] for i in idx)


def join_tight(data: dict, idx: list[int]) -> str:
    """ต่อชิดกันหมด — เสียช่องว่างที่ควรมีจริง"""
    return "".join(data["text"][i] for i in idx)


def join_by_gap(data: dict, idx: list[int], ratio: float = 0.28) -> str:
    """ดูระยะห่างจริงระหว่างกรอบ ถ้าห่างเกินสัดส่วนของความสูงตัวอักษรจึงใส่ช่องว่าง

    ภาษาไทยเขียนติดกันภายในวลี ช่องว่างจริงจึงกว้างกว่าระยะระหว่าง cluster มาก
    """
    idx = sorted(idx, key=lambda i: data["left"][i])
    out: list[str] = []
    prev_right: int | None = None
    for i in idx:
        left, width = data["left"][i], data["width"][i]
        height = data["height"][i] or 1
        if prev_right is not None:
            gap = left - prev_right
            if gap > height * ratio:
                out.append(" ")
        out.append(data["text"][i])
        prev_right = left + width
    return "".join(out)


def main() -> None:
    setup()
    image_path = IMAGE_DIR / f"{PAGE}.png"
    print(f"หน้า {PAGE}\n")

    configs = {
        "psm 6": "--oem 1 --psm 6",
        "psm 6 + preserve_spaces": "--oem 1 --psm 6 -c preserve_interword_spaces=1",
        "psm 4": "--oem 1 --psm 4",
    }

    for label, config in configs.items():
        with Image.open(image_path) as image:
            raw = pytesseract.image_to_string(image, lang="tha+eng", config=config)
            data = pytesseract.image_to_data(
                image, lang="tha+eng", config=config, output_type=pytesseract.Output.DICT
            )

        lines = group_lines(data)
        if not lines:
            print(f"### {label}: ไม่พบข้อความ\n")
            continue
        first = lines[LINE_INDEX]

        print(f"### {label}")
        raw_line = next((ln for ln in raw.splitlines() if ln.strip()), "")
        print(f"  image_to_string : {raw_line[:95]}")
        print(f"  join แบบเดิม     : {join_naive(data, first)[:95]}")
        print(f"  join ชิดหมด      : {join_tight(data, first)[:95]}")
        print(f"  join ตามระยะห่าง : {join_by_gap(data, first)[:95]}")
        print(f"  จำนวนชิ้นในบรรทัด: {len(first)}")
        print()


if __name__ == "__main__":
    main()
