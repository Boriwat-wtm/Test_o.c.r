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
        # ต้องเช็กถึงระดับที่ใช้จริง — _load() ส่ง device_map="cuda:0"
        # ซึ่ง transformers บังคับให้มี accelerate ถ้าขาดจะรายงานว่าพร้อมใช้
        # แล้วไปพังตอนโหลดโมเดลทุกหน้า (เจอมาแล้วตอนรันทั้งชุด)
        from importlib.util import find_spec

        if find_spec("accelerate") is None:
            return False, "ยังไม่ได้ติดตั้ง accelerate (device_map ต้องใช้)"
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

    def _prepare_inputs(self, image_path: Path) -> Any:
        """เปิดภาพ ย่อขนาด แล้วประกอบเป็น input tensor พร้อมป้อนโมเดล

        แยกออกมาจาก _run() เพราะ read_variants() ต้องใช้ input ชุดเดียวกัน
        แค่เปลี่ยนวิธี sample ตอน generate — ไม่อยากให้ภาพถูกย่อหรือ prompt
        เพี้ยนไม่ตรงกันระหว่างสองเส้นทางนี้
        """
        from PIL import Image

        _, processor = self._load()
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
            return processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self._model.device)

    def read_variants(
        self, image_path: Path, *, n: int = 3, temperature: float = 0.3
    ) -> list[str]:
        """อ่านภาพเดิมซ้ำ n รอบแบบสุ่ม (ไม่ใช่ greedy) คืนข้อความทุกรอบ

        เอาไว้เช็ก self-consistency โดยไม่ต้องพึ่ง engine อื่นเลย — จุดที่โมเดล
        ไม่มั่นใจจริง คำตอบมักแกว่งไปมาระหว่างรอบที่เปิด sampling ส่วนจุดที่
        มั่นใจ คำตอบจะซ้ำเดิมแม้เปิด sampling ก็ตาม เป็นสัญญาณคนละแบบกับ
        confidence ระดับ token ใน _run() (ตัวนั้นดูตอนสร้างครั้งเดียว
        ตัวนี้ดูว่าสร้างซ้ำแล้วยังตอบเหมือนเดิมไหม) ใช้เสริมกันได้

        เปิด do_sample=True เฉพาะเมธอดนี้ ไม่แตะ _run() หลัก เพราะการรันจริง
        เพื่อเก็บผลเปรียบเทียบต้องได้ผลเดิมทุกครั้ง (ดูเหตุผลใน _run())
        ตั้งใจไม่ขอ output_scores ในนี้ เพราะจุดประสงค์คือดูว่าข้อความต่างกัน
        ไหม ไม่ใช่ดูความน่าจะเป็นของ token ซึ่งกินหน่วยความจำเพิ่มโดยไม่จำเป็น
        """
        import torch

        model, processor = self._load()
        inputs = self._prepare_inputs(image_path)

        texts = []
        for _ in range(n):
            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=True,
                    temperature=temperature,
                    repetition_penalty=1.05,
                )
            trimmed = generated[0][inputs["input_ids"].shape[1] :]
            texts.append(processor.decode(trimmed, skip_special_tokens=True).strip())
        return texts

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        import torch

        model, processor = self._load()
        inputs = self._prepare_inputs(image_path)

        started = time.perf_counter()
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
                # เอาความน่าจะเป็นของแต่ละ token ที่เลือกจริงมาด้วย เพื่อใช้แทน
                # confidence ที่ VLM ไม่มีให้มาแบบ engine ตรวจจับ+อ่านทั่วไป
                output_scores=True,
                return_dict_in_generate=True,
            )
        core_ms = (time.perf_counter() - started) * 1000

        trimmed = generated.sequences[0][inputs["input_ids"].shape[1] :]
        text = processor.decode(trimmed, skip_special_tokens=True)

        token_ids = trimmed.tolist()
        token_probs = [
            torch.softmax(step[0], dim=-1)[tid].item()
            for step, tid in zip(generated.scores, token_ids)
        ]
        raw_lines = text.split("\n")
        line_confs = _line_confidences(processor, token_ids, token_probs)
        # สองฝั่งต้องหั่นด้วย "\n" เท่ากันเป๊ะถึงจะจับคู่ตรงบรรทัด ถ้าไม่เท่ากัน
        # ยอมเสีย confidence ทั้งหน้าดีกว่าจับคู่ผิดแล้วติดป้ายความมั่นใจผิดบรรทัด
        # (แนวทางเดียวกับที่ tesseract_tha.py ใช้กับกรอบตำแหน่ง)
        aligned = len(raw_lines) == len(line_confs)

        # VLM ไม่คืนกรอบตำแหน่ง หน้าเว็บจะชี้ตำแหน่งของ engine นี้ไม่ได้
        # (ต้องยืมจาก engine อื่นที่บรรทัดตรงกัน ดู suspect.scan_page)
        lines = [
            OcrLine(text=ln.strip(), confidence=line_confs[i] if aligned else None)
            for i, ln in enumerate(raw_lines)
            if ln.strip()
        ]
        return lines, core_ms


def _line_confidences(
    processor: Any, token_ids: list[int], token_probs: list[float]
) -> list[float]:
    """เฉลี่ยความน่าจะเป็นระดับ token ให้เหลือค่าเดียวต่อบรรทัด

    ถอด token ทีละตัวเดี่ยว ๆ ไม่ได้ตรง ๆ เพราะ tokenizer แบบ byte-level อาจตัด
    อักขระไทยหนึ่งตัว (UTF-8 หลายไบต์) คร่อมหลาย token ถอดเดี่ยว ๆ จะได้ตัวแทน
    (U+FFFD) ปนมา จึงถอดเป็นหน้าต่างเลื่อนแล้วดูส่วนต่างที่เพิ่มมาแทน — วิธีเดียว
    กับที่ใช้ทำ token streaming ทั่วไป
    """
    window = 6
    line_probs: list[list[float]] = [[]]
    for i, p in enumerate(token_probs):
        lo = max(0, i - window + 1)
        cur = processor.decode(token_ids[lo : i + 1], skip_special_tokens=True)
        prev = processor.decode(token_ids[lo:i], skip_special_tokens=True)
        added = cur[len(prev):] if cur.startswith(prev) else cur
        for ch in added:
            if ch == "\n":
                line_probs.append([])
            else:
                line_probs[-1].append(p)
    return [sum(v) / len(v) if v else 1.0 for v in line_probs]


register(TyphoonOcr())
