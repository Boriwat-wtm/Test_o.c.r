"""Tesseract 5 ภาษาไทย

ใช้ tessdata_best ที่ดาวน์โหลดไว้ใน vendor/tessdata เพื่อไม่ต้องแตะโฟลเดอร์
ใน Program Files (ซึ่งต้องสิทธิ์ admin) และเพื่อให้ทุกเครื่องได้ไฟล์รุ่นเดียวกัน
"""

from __future__ import annotations

import os
from pathlib import Path

import pytesseract
from PIL import Image

from ..config import TESSDATA_DIR, TESSERACT_EXE
from .base import Engine, OcrLine, register


class TesseractThai(Engine):
    name = "tesseract-tha"
    label = "Tesseract 5 (tha)"
    needs_gpu = False

    # --psm 6 = ถือว่าทั้งภาพเป็นบล็อกข้อความเดียว เหมาะกับเอกสารคอลัมน์เดียว
    config = "--oem 1 --psm 6"

    def available(self) -> tuple[bool, str]:
        if not TESSERACT_EXE.exists():
            return False, f"ไม่พบ tesseract.exe ที่ {TESSERACT_EXE}"
        if not (TESSDATA_DIR / "tha.traineddata").exists():
            return False, f"ไม่พบ tha.traineddata ใน {TESSDATA_DIR}"
        return True, ""

    def _run(self, image_path: Path) -> list[OcrLine]:
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

        with Image.open(image_path) as image:
            data = pytesseract.image_to_data(
                image,
                lang="tha+eng",
                config=self.config,
                output_type=pytesseract.Output.DICT,
            )

        # รวมคำที่อยู่บรรทัดเดียวกันกลับเป็นบรรทัด พร้อมกรอบที่ครอบทั้งบรรทัด
        grouped: dict[tuple[int, int, int, int], list[int]] = {}
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

        lines: list[OcrLine] = []
        for indexes in grouped.values():
            words = [data["text"][i] for i in indexes]
            confs = [float(data["conf"][i]) for i in indexes if float(data["conf"][i]) >= 0]
            x0 = min(data["left"][i] for i in indexes)
            y0 = min(data["top"][i] for i in indexes)
            x1 = max(data["left"][i] + data["width"][i] for i in indexes)
            y1 = max(data["top"][i] + data["height"][i] for i in indexes)
            lines.append(
                OcrLine(
                    text=" ".join(words),
                    confidence=(sum(confs) / len(confs) / 100) if confs else None,
                    box=(x0, y0, x1 - x0, y1 - y0),
                )
            )

        # เรียงจากบนลงล่าง เพื่อให้ลำดับการอ่านตรงกับที่คนอ่าน
        lines.sort(key=lambda ln: (ln.box[1] if ln.box else 0))
        return lines


register(TesseractThai())
