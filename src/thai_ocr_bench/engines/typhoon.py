"""Typhoon OCR 1.5 (2B) — ตัวแทนฝั่ง vision-language model

เลือกรุ่น 2B ไม่ใช่ 7B เพราะเครื่องมี VRAM 6 GB
7B แบบ fp16 ต้องราว 15 GB ส่วน 4-bit ราว 4.5 GB เฉพาะน้ำหนัก
ยังไม่รวม vision token ของภาพเอกสารซึ่งกินอีกมาก จึงเสี่ยง OOM

ข้อควรรู้เวลาอ่านผล: VLM ต่างจาก OCR แบบเดิมตรงที่มันอาจ "แต่ง" ข้อความ
ให้ดูสมเหตุสมผลแทนที่จะอ่านตามภาพ เลขที่หนังสือหรือจำนวนเงินที่ผิด
จะดูเนียนกว่าของ OCR แบบเดิมมาก ต้องอ่านผลเทียบภาพจริงเสมอ
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .base import Engine, OcrLine, register

MODEL_ID = "typhoon-ai/typhoon-ocr1.5-2b"

# ย่อภาพก่อนเข้าโมเดลเพื่อคุมจำนวน vision token ให้พอกับ VRAM 6 GB
# ภาพต้นฉบับ 300 DPI คือ 2480x3507 ซึ่งใหญ่เกินไปสำหรับการ์ดใบนี้
# ค่านี้กระทบความแม่น จึงต้องบันทึกไว้ในรายงานด้วย
MAX_SIDE = 1536

# หน้าเอกสารไทยหนึ่งหน้าเต็มอยู่ราว 1,000-1,500 token
# ตั้งเพดานไว้ 2,048 เพื่อให้ยังอ่านหน้าที่แน่นได้ครบ แต่ถ้าติดลูปก็หยุดเร็ว
# ค่าเดิม 4,096 ทำให้หน้าที่ติดลูปกินเวลา 320 วินาที
MAX_NEW_TOKENS = 2048

PROMPT = (
    "อ่านข้อความทั้งหมดในภาพเอกสารนี้ออกมาเป็นข้อความธรรมดา "
    "คงลำดับบรรทัดตามต้นฉบับ หนึ่งบรรทัดในภาพคือหนึ่งบรรทัดในผลลัพธ์ "
    "คงรูปแบบตัวเลขตามที่เห็น ถ้าเป็นเลขไทยให้คงเป็นเลขไทย "
    "ห้ามแปล ห้ามสรุป ห้ามเติมข้อความที่ไม่มีในภาพ "
    "ห้ามใส่เครื่องหมาย markdown"
)


class TyphoonOcr(Engine):
    name = "typhoon-2b"
    label = "Typhoon OCR 1.5 (2B)"
    needs_gpu = True

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import torch
            import transformers  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง transformers/torch ({exc})"
        if not torch.cuda.is_available():
            return False, "ต้องมี GPU (torch มองไม่เห็น CUDA)"
        return True, ""

    def _load(self) -> tuple[Any, Any]:
        if self._model is None:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(MODEL_ID)
            self._model = AutoModelForImageTextToText.from_pretrained(
                MODEL_ID,
                dtype=torch.float16,
                device_map="cuda:0",
            )
            self._model.eval()
        return self._model, self._processor

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        import torch
        from PIL import Image

        model, processor = self._load()

        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
            scale = MAX_SIDE / max(image.size)
            if scale < 1:
                image = image.resize(
                    (round(image.width * scale), round(image.height * scale)),
                    Image.LANCZOS,
                )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ]

            started = time.perf_counter()
            inputs = processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            ).to(model.device)

            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=False,  # ต้องได้ผลเดิมทุกครั้งเพื่อให้เทียบได้
                    # กันอาการติดลูป
                    #
                    # หน้าที่มีลายน้ำซ้ำ ๆ ทำให้โมเดลวนพ่นข้อความลายน้ำเดิม
                    # 123 บรรทัดจนชนเพดาน token ใช้เวลา 320 วินาทีต่อหน้า
                    # ตั้งค่าปรับโทษการซ้ำเล็กน้อย ไม่ให้แรงเกินจนตัวเลข
                    # หรือคำที่ซ้ำโดยธรรมชาติในเอกสารถูกกดหาย
                    repetition_penalty=1.05,
                )
            core_ms = (time.perf_counter() - started) * 1000

        trimmed = generated[0][inputs["input_ids"].shape[1] :]
        text = processor.decode(trimmed, skip_special_tokens=True)

        # VLM ไม่คืนกรอบตำแหน่ง หน้าเว็บจะชี้ตำแหน่งของ engine นี้ไม่ได้
        lines = [
            OcrLine(text=ln.strip())
            for ln in text.splitlines()
            if ln.strip()
        ]
        return lines, core_ms


register(TyphoonOcr())
