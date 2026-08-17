"""Tesseract 5 ภาษาไทย

ใช้ tessdata_best ที่ดาวน์โหลดไว้ใน vendor/tessdata เพื่อไม่ต้องแตะโฟลเดอร์
ใน Program Files (ซึ่งต้องสิทธิ์ admin) และเพื่อให้ทุกเครื่องได้ไฟล์รุ่นเดียวกัน
"""

from __future__ import annotations

import os
import time
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

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

        with Image.open(image_path) as image:
            # ข้อความเอาจาก image_to_string เท่านั้น
            #
            # image_to_data คืนคำไทยมาเป็นชิ้นย่อยระดับ cluster (บรรทัดเดียวอาจ 61 ชิ้น)
            # เพราะไทยไม่มีขอบเขตคำ ถ้าเอาชิ้นพวกนั้นมาต่อด้วยช่องว่างจะได้
            # 'ม ิ ต ิ ด ้ า น' ส่วน image_to_string ใช้ตรรกะเว้นวรรคของ Tesseract เอง
            # จึงได้ 'มิติด้าน' ที่ถูกต้อง — ใช้ image_to_data แค่เอากรอบกับ confidence
            started = time.perf_counter()
            raw_text = pytesseract.image_to_string(
                image, lang="tha+eng", config=self.config
            )
            core_ms = (time.perf_counter() - started) * 1000

            # รอบที่สองมีไว้ให้หน้าเว็บชี้ตำแหน่งได้ ไม่นับเป็นเวลาใช้งานจริง
            data = pytesseract.image_to_data(
                image,
                lang="tha+eng",
                config=self.config,
                output_type=pytesseract.Output.DICT,
            )

        text_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        boxes = self._line_boxes(data)

        # ทั้งสองฝั่งมาจากการวิเคราะห์เลย์เอาต์ครั้งเดียวกัน ลำดับบรรทัดจึงตรงกัน
        # ถ้าจำนวนไม่ตรง (เกิดได้ยาก) ยอมเสียกรอบไป ดีกว่าจับคู่ผิดแล้วชี้ตำแหน่งมั่ว
        aligned = len(text_lines) == len(boxes)
        lines = [
            OcrLine(
                text=text,
                confidence=boxes[i][0] if aligned else None,
                box=boxes[i][1] if aligned else None,
            )
            for i, text in enumerate(text_lines)
        ]
        return lines, core_ms

    @staticmethod
    def _line_boxes(data: dict) -> list[tuple[float | None, tuple[int, int, int, int]]]:
        """รวมชิ้นส่วนในบรรทัดเดียวกันเป็นกรอบเดียว เรียงจากบนลงล่าง"""
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

        out: list[tuple[float | None, tuple[int, int, int, int]]] = []
        for indexes in grouped.values():
            confs = [float(data["conf"][i]) for i in indexes if float(data["conf"][i]) >= 0]
            x0 = min(data["left"][i] for i in indexes)
            y0 = min(data["top"][i] for i in indexes)
            x1 = max(data["left"][i] + data["width"][i] for i in indexes)
            y1 = max(data["top"][i] + data["height"][i] for i in indexes)
            out.append(
                (
                    (sum(confs) / len(confs) / 100) if confs else None,
                    (x0, y0, x1 - x0, y1 - y0),
                )
            )

        out.sort(key=lambda item: item[1][1])
        return out


register(TesseractThai())
