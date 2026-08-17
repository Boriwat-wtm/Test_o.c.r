"""Surya OCR — รองรับ 90+ ภาษารวมภาษาไทย พร้อม layout และลำดับการอ่าน

เหตุผลที่ใส่เข้ามา: PaddleOCR อ่านครบแค่ 70% ของบรรทัดและพ่นบรรทัดเกิน 438 บรรทัด
เพราะลายน้ำกวนตัวตรวจจับ Surya ทำ layout analysis มาด้วย จึงน่าจะรับมือได้ดีกว่า

API ของ Surya เปลี่ยนหลายรอบระหว่างเวอร์ชัน โค้ดนี้จึงลองหลายรูปแบบ
แล้วจำไว้ว่ารูปแบบไหนใช้ได้ ดีกว่าล็อกกับ API เดียวแล้วพังตอนอัปเกรด
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .base import Engine, OcrLine, register


class SuryaOcr(Engine):
    name = "surya"
    label = "Surya OCR"
    needs_gpu = True

    def __init__(self) -> None:
        self._rec: Any = None
        self._det: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import surya  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง surya-ocr ({exc})"
        return True, ""

    def _load(self) -> tuple[Any, Any]:
        if self._rec is not None:
            return self._rec, self._det

        from surya.detection import DetectionPredictor
        from surya.recognition import RecognitionPredictor

        self._det = DetectionPredictor()
        try:
            # เวอร์ชันใหม่ (0.16+) แยกน้ำหนักส่วนร่วมออกมาเป็น FoundationPredictor
            from surya.foundation import FoundationPredictor

            self._rec = RecognitionPredictor(FoundationPredictor())
        except (ImportError, TypeError):
            # เวอร์ชันเก่าสร้างตรง ๆ ได้เลย
            self._rec = RecognitionPredictor()

        return self._rec, self._det

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        from PIL import Image

        rec, det = self._load()

        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
            started = time.perf_counter()
            predictions = _predict(rec, det, image)
            core_ms = (time.perf_counter() - started) * 1000

        lines: list[OcrLine] = []
        for page in predictions or []:
            for line in getattr(page, "text_lines", []) or []:
                text = getattr(line, "text", "") or ""
                if not text.strip():
                    continue
                lines.append(
                    OcrLine(
                        text=text,
                        confidence=getattr(line, "confidence", None),
                        box=_to_box(getattr(line, "bbox", None)),
                    )
                )

        lines.sort(key=lambda ln: (ln.box[1] if ln.box else 0, ln.box[0] if ln.box else 0))
        return lines, core_ms


def _predict(rec: Any, det: Any, image: Any) -> Any:
    """เรียก recognition predictor โดยลองรูปแบบที่ Surya ใช้ในเวอร์ชันต่าง ๆ"""
    attempts = (
        lambda: rec([image], det_predictor=det),
        lambda: rec([image], [None], det),
        lambda: rec([image], [["th", "en"]], det),
    )
    last: Exception | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last = exc
    raise RuntimeError(f"เรียก Surya ไม่สำเร็จทุกรูปแบบ: {last}")


def _to_box(bbox: Any) -> tuple[int, int, int, int] | None:
    if not bbox:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return None
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


register(SuryaOcr())
