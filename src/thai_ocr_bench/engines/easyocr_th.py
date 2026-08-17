"""EasyOCR ภาษาไทย — ตัวคุมของการทดลอง

ใส่ตัวนี้เข้ามาเพราะรู้ล่วงหน้าแล้วว่ามันมีข้อจำกัดที่วัดได้ชัด
ตรวจ charset ของโมเดล thai_g1 ใน easyocr/config.py แล้วพบว่าลงท้ายด้วย

    ...ฯๆ0123456789๑๒๓๔๕๖๗๘๙

มี ๑ ถึง ๙ แต่ **ไม่มี ๐** ตัวถอดรหัส CTC เลือกได้แค่อักขระใน charset
ดังนั้นเลขอย่าง ๑๐ ๒๐ ๒๕๖๙ จะพลาดทุกครั้งอย่างเป็นระบบ ไม่ใช่พลาดแบบสุ่ม

ผลของมันจึงมีค่าสองอย่าง — ยืนยันข้อค้นพบเรื่อง ๐ เป็นตัวเลขจริง
และเป็นเส้นฐานว่า OCR ที่ charset ไม่ครบให้ผลแย่แค่ไหน
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..config import VENDOR_DIR
from .base import Engine, OcrLine, register

MODEL_DIR = VENDOR_DIR / "cache" / "easyocr"


class EasyOcrThai(Engine):
    name = "easyocr-th"
    label = "EasyOCR (th)"
    needs_gpu = True

    def __init__(self) -> None:
        self._reader: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import easyocr  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง easyocr ({exc})"
        return True, ""

    def _engine(self) -> Any:
        if self._reader is None:
            import easyocr
            import torch

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            self._reader = easyocr.Reader(
                ["th", "en"],
                gpu=torch.cuda.is_available(),
                # บังคับที่เก็บโมเดลไว้ในโปรเจกต์ ไม่ให้ไปลงไดรฟ์ C
                model_storage_directory=str(MODEL_DIR),
                user_network_directory=str(MODEL_DIR),
            )
        return self._reader

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        reader = self._engine()

        started = time.perf_counter()
        raw = reader.readtext(str(image_path))
        core_ms = (time.perf_counter() - started) * 1000

        lines: list[OcrLine] = []
        for item in raw:
            if len(item) < 3:
                continue
            box, text, conf = item[0], item[1], item[2]
            if not str(text).strip():
                continue
            lines.append(
                OcrLine(
                    text=str(text),
                    confidence=float(conf),
                    box=_to_box(box),
                )
            )

        lines.sort(key=lambda ln: (ln.box[1] if ln.box else 0, ln.box[0] if ln.box else 0))
        return lines, core_ms


def _to_box(poly: Any) -> tuple[int, int, int, int] | None:
    try:
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
    except (TypeError, IndexError, ValueError):
        return None
    if not xs:
        return None
    x0, y0 = int(min(xs)), int(min(ys))
    return x0, y0, int(max(xs)) - x0, int(max(ys)) - y0


register(EasyOcrThai())
