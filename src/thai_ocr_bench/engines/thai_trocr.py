"""ThaiTrOCR — kkatiz/thai-trocr-thaigov-v2

เลือกรุ่นนี้จากหลายตัวบน HuggingFace เพราะ fine-tune บน ThaiGov V2 Corpus
คือคลังข้อความเอกสารราชการไทย ตรงกับงานนี้ที่สุด
(สถาปัตยกรรม: TrOCR-base-handwritten เป็นตัวมอง + WangchanBERTa เป็นตัวเขียน)

ข้อจำกัดสำคัญ: TrOCR อ่านได้เฉพาะ "ภาพหนึ่งบรรทัด" ไม่ใช่ทั้งหน้า
จึงต้องมีตัวตรวจจับมาหั่นบรรทัดให้ก่อน ตัวนี้ยืมตัวตรวจจับของ PaddleOCR มาใช้

ผลที่ได้จึงเป็นของ "ตัวตรวจจับ Paddle + ตัวอ่าน TrOCR" ไม่ใช่ TrOCR ล้วน
ถ้าค่า recall ออกมาใกล้ paddle-th แปลว่าข้อจำกัดอยู่ที่ตัวตรวจจับร่วมกัน
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .base import Engine, OcrLine, register

MODEL_ID = "kkatiz/thai-trocr-thaigov-v2"

# TrOCR ถูกเทรนกับภาพบรรทัดสูงราว 32-64 px ถ้าเล็กเกินจะอ่านไม่ออก
MIN_LINE_HEIGHT = 12
MAX_LINES_PER_PAGE = 200  # กันหน้าที่ตัวตรวจจับแตกเป็นพันชิ้น


class ThaiTrOcr(Engine):
    name = "thai-trocr"
    label = "ThaiTrOCR (thaigov-v2)"
    needs_gpu = True

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._detector: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import torch
            import transformers  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง transformers/torch ({exc})"
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False, "ต้องมี paddleocr เพื่อใช้ตัวตรวจจับบรรทัด"
        if not torch.cuda.is_available():
            return False, "ต้องมี GPU (torch มองไม่เห็น CUDA)"
        return True, ""

    def _load(self) -> tuple[Any, Any, Any]:
        if self._model is None:
            import os

            import torch
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel

            os.environ.setdefault("FLAGS_use_mkldnn", "0")
            from paddleocr import TextDetection

            self._processor = TrOCRProcessor.from_pretrained(MODEL_ID)
            self._model = VisionEncoderDecoderModel.from_pretrained(
                MODEL_ID, dtype=torch.float16
            ).to("cuda:0")
            self._model.eval()
            self._detector = TextDetection(model_name="PP-OCRv5_mobile_det")
        return self._model, self._processor, self._detector

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        import torch
        from PIL import Image

        model, processor, detector = self._load()

        started = time.perf_counter()
        detected = detector.predict(str(image_path))
        boxes: list[tuple[int, int, int, int]] = []
        for page in detected or []:
            data = page if isinstance(page, dict) else getattr(page, "res", page)
            for poly in data.get("dt_polys") or []:
                box = _to_box(poly)
                if box and box[3] >= MIN_LINE_HEIGHT:
                    boxes.append(box)

        boxes.sort(key=lambda b: (b[1], b[0]))
        boxes = boxes[:MAX_LINES_PER_PAGE]

        lines: list[OcrLine] = []
        with Image.open(image_path) as raw:
            page_image = raw.convert("RGB")
            for x, y, w, h in boxes:
                crop = page_image.crop((x, y, x + w, y + h))
                pixels = processor(images=crop, return_tensors="pt").pixel_values
                pixels = pixels.to(model.device, dtype=model.dtype)
                with torch.inference_mode():
                    generated = model.generate(pixels, max_new_tokens=96)
                text = processor.batch_decode(generated, skip_special_tokens=True)[0]
                if text.strip():
                    lines.append(OcrLine(text=text.strip(), box=(x, y, w, h)))

        core_ms = (time.perf_counter() - started) * 1000
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


register(ThaiTrOcr())
