"""Surya OCR 0.17.1 — รองรับ 90+ ภาษารวมภาษาไทย

เหตุผลที่ใส่เข้ามา: PaddleOCR อ่านครบแค่ 70% ของบรรทัดและพ่นบรรทัดเกินมาก
เพราะลายน้ำกวนตัวตรวจจับ Surya อาจแยกลายน้ำออกจากเนื้อหาได้ดีกว่า

สถานะปัจจุบัน: ยังใช้ไม่ได้ในสภาพแวดล้อมนี้ ทดลองแล้วสองทางและตันทั้งคู่

  surya 0.17.1 (และเก่ากว่า)  รันบน torch ในเครื่องตรง ๆ ตามที่เราต้องการ
      แต่ล้มด้วย AttributeError: 'SuryaDecoderConfig' object has no attribute
      'pad_token_id' เพราะเข้ากันไม่ได้กับ transformers 5.x
      (ประกาศไว้ว่า transformers>=4.56.1 แบบไม่มีเพดานบน ซึ่งไม่ตรงความจริง)
      จะใช้ได้ต้องถอย transformers ลงเป็น 4.x ซึ่งทำให้ Typhoon พังแทน
      เพราะ Qwen3-VL ต้องใช้ 5.x

  surya 0.21.2 / 0.22.1  เข้ากันได้กับ transformers 5.x
      แต่เปลี่ยนไปรันโมเดลผ่าน container ล้มด้วย
      SpawnError: docker binary not found

ทางที่เหลือถ้าอยากใช้จริง — ติดตั้ง Docker Desktop หรือแยก venv ให้ Surya
ตัวเดียว ทั้งสองทางเกินความจำเป็นเมื่อเทียบกับที่ได้เพิ่ม จึงพักไว้ก่อน

อีกเรื่องที่ต้องรู้: Surya ไม่เคารพ HF_HOME มันเก็บโมเดลไว้ที่ของตัวเอง
ผ่านค่า MODEL_CACHE_DIR ซึ่งชี้ไปไดรฟ์ C โดยปริยาย โมดูล __init__ ของโปรเจกต์
จึงตั้งตัวแปรนั้นให้ชี้มา vendor/cache/surya แล้ว
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .base import Engine, OcrLine, register


class SuryaOcr(Engine):
    name = "surya"
    label = "Surya OCR 0.17"
    needs_gpu = True

    def __init__(self) -> None:
        self._rec: Any = None
        self._det: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            from surya.recognition import RecognitionPredictor
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง surya-ocr ({exc})"

        # เวอร์ชัน 0.21 ขึ้นไปรันโมเดลผ่าน container ต้องมี Docker ในเครื่อง
        # ตรวจจากลายเซ็นของ __init__ ที่รับ SuryaInferenceManager
        import inspect
        import shutil

        params = inspect.signature(RecognitionPredictor.__init__).parameters
        if "manager" in params and shutil.which("docker") is None:
            return False, "surya รุ่นนี้ต้องมี Docker (ดูหมายเหตุในไฟล์นี้)"

        try:
            import torch
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง torch ({exc})"
        if not torch.cuda.is_available():
            return False, "ต้องมี GPU (torch มองไม่เห็น CUDA)"
        return True, ""

    def _load(self) -> tuple[Any, Any]:
        if self._rec is None:
            from surya.detection import DetectionPredictor
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor

            self._rec = RecognitionPredictor(FoundationPredictor())
            self._det = DetectionPredictor()
        return self._rec, self._det

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        from PIL import Image

        rec, det = self._load()

        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
            started = time.perf_counter()
            predictions = rec(
                [image],
                det_predictor=det,
                sort_lines=True,  # ให้เรียงตามลำดับการอ่านมาให้เลย
                math_mode=False,  # เอกสารราชการไม่มีสมการ ปิดไว้ลดโอกาสเพี้ยน
            )
            core_ms = (time.perf_counter() - started) * 1000

        lines: list[OcrLine] = []
        for page in predictions if predictions is not None else []:
            for line in getattr(page, "text_lines", None) or []:
                text = (getattr(line, "text", "") or "").strip()
                if not text:
                    continue
                lines.append(
                    OcrLine(
                        text=text,
                        confidence=getattr(line, "confidence", None),
                        box=_to_box(getattr(line, "bbox", None)),
                    )
                )
        return lines, core_ms


def _to_box(bbox: Any) -> tuple[int, int, int, int] | None:
    if bbox is None:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in list(bbox)[:4])
    except (TypeError, ValueError):
        return None
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


register(SuryaOcr())
