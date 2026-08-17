"""PaddleOCR ภาษาไทย — ใช้โมเดล th_PP-OCRv5_mobile_rec

ตัวนี้เป็นตัวเต็งของฝั่ง on-prem เพราะตรวจ dictionary ของโมเดลแล้วพบว่า
มีเลขไทยครบทั้ง ๐-๙ และมีอักษรไทย 72 ตัว ต่างจาก PP-OCRv6 ที่ไม่มีอักษรไทยเลย

ปิดโมดูลเสริมทั้งหมด (จัดหน้าเอกสาร แก้ภาพบิด หมุนบรรทัด) เพราะ
  - ภาพจาก render.py ตั้งตรงและไม่บิดอยู่แล้ว
  - ยิ่งเปิดหลายชั้น ยิ่งแยกไม่ออกว่าความผิดมาจากตัวอ่านหรือตัวเตรียมภาพ
  - โหลดโมเดลเพิ่มโดยไม่จำเป็น
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .base import Engine, OcrLine, register


class PaddleThai(Engine):
    name = "paddle-th"
    label = "PaddleOCR (th_PP-OCRv5)"
    needs_gpu = False

    def __init__(self) -> None:
        self._ocr: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import paddleocr  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง paddleocr ({exc})"
        return True, ""

    def _engine(self) -> Any:
        """สร้างครั้งเดียวแล้วใช้ซ้ำ — การโหลดโมเดลกินเวลาหลายวินาที"""
        if self._ocr is None:
            # ต้องปิด oneDNN ก่อน import paddle
            #
            # PaddlePaddle 3.3.1 บน Windows CPU พังตอนรันด้วย
            #   NotImplementedError: ConvertPirAttribute2RuntimeAttribute
            #   not support [pir::ArrayAttribute<pir::DoubleAttribute>]
            # ซึ่งมาจากตัวแปลงกราฟของ oneDNN ในเอนจินตัวใหม่ (PIR)
            # ปิดแล้วกลับไปใช้เส้นทางปกติซึ่งทำงานได้
            os.environ.setdefault("FLAGS_use_mkldnn", "0")

            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang="th",
                # ต้องระบุตัวตรวจจับเอง ไม่งั้น lang='th' จะไปหยิบ PP-OCRv5_server_det
                # ซึ่งใหญ่กว่ามากและกินเวลา 234 วินาทีต่อหน้าบน CPU
                # ส่วนตัวอ่านข้อความ th_PP-OCRv5_mobile_rec เป็น mobile อยู่แล้ว
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="th_PP-OCRv5_mobile_rec",
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._ocr

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        ocr = self._engine()  # ไม่นับเวลาโหลดโมเดลเป็นเวลาอ่านหน้า

        started = time.perf_counter()
        results = ocr.predict(str(image_path))
        core_ms = (time.perf_counter() - started) * 1000

        lines: list[OcrLine] = []
        for page in results if results is not None else []:
            data = page if isinstance(page, dict) else getattr(page, "res", page)
            # ห้ามใช้ `or []` กับค่าที่ Paddle คืนมา เพราะบางคีย์เป็น numpy array
            # การเช็คความจริงของ array หลายสมาชิกทำให้ ValueError
            texts = _as_list(data.get("rec_texts"))
            scores = _as_list(data.get("rec_scores"))
            polys = data.get("rec_polys")
            if polys is None:
                polys = data.get("dt_polys")
            polys = _as_list(polys)

            for i, text in enumerate(texts):
                if not str(text).strip():
                    continue
                lines.append(
                    OcrLine(
                        text=str(text),
                        confidence=float(scores[i]) if i < len(scores) else None,
                        box=_to_box(polys[i]) if i < len(polys) else None,
                    )
                )

        # PaddleOCR คืนผลตามลำดับที่ตรวจเจอ ไม่ใช่ลำดับการอ่าน จึงต้องเรียงเอง
        lines.sort(key=lambda ln: (ln.box[1] if ln.box else 0, ln.box[0] if ln.box else 0))
        return lines, core_ms


def _as_list(value: Any) -> list:
    """แปลงค่าที่ Paddle คืนมาเป็น list โดยไม่แตะความจริงของ numpy array"""
    if value is None:
        return []
    return list(value)


def _to_box(poly: Any) -> tuple[int, int, int, int] | None:
    """แปลงสี่เหลี่ยมสี่มุมของ Paddle เป็นกรอบ (x, y, กว้าง, สูง)"""
    try:
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
    except (TypeError, IndexError, ValueError):
        return None
    if not xs or not ys:
        return None
    x0, y0 = int(min(xs)), int(min(ys))
    return x0, y0, int(max(xs)) - x0, int(max(ys)) - y0


register(PaddleThai())
