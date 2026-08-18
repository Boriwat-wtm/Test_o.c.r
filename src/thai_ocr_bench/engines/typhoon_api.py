"""Typhoon OCR ผ่าน API ของ opentyphoon.ai — ไม่ใช้ GPU ในเครื่องเลย

มีไว้เพราะเครื่องมี VRAM แค่ 6 GB ซึ่งพอดีตัวสำหรับรุ่น 2B เท่านั้น
และตอนรันจริง GPU ถูกใช้ 98% นานหลายนาทีต่อหน้า ทำอย่างอื่นไม่ได้เลย
ตัวนี้ยิงไปที่เซิร์ฟเวอร์ของ Typhoon แทน เครื่องแทบไม่ทำงาน

ข้อดีเพิ่มเติมนอกจากไม่กิน VRAM
  - ย่อภาพเหลือ 1800 px ได้ (รุ่นในเครื่องต้องย่อเหลือ 1536 เพราะ VRAM ไม่พอ)
    ภาพใหญ่กว่าแปลว่าตัวหนังสือเล็ก ๆ กับวรรณยุกต์ชัดกว่า
  - เลือกโมเดล 7B ได้ ซึ่งเครื่องนี้รันเองไม่ไหว

ข้อควรรู้ก่อนใช้
  - เอกสารถูกส่งออกนอกเครื่อง ไปอยู่บนเซิร์ฟเวอร์ของผู้ให้บริการ
    เอกสารชุดทดสอบตอนนี้เป็นกฎหมายกับประกาศบริษัทที่เผยแพร่สาธารณะอยู่แล้ว
    แต่ถ้าจะใช้กับหนังสือราชการจริงที่มีข้อมูลส่วนบุคคล ต้องตัดสินใจใหม่
  - ต้องมี API key ตั้งไว้ในตัวแปรแวดล้อม TYPHOON_OCR_API_KEY
    (ขอฟรีได้ที่ opentyphoon.ai — เป็น research showcase ไม่มีค่าใช้จ่าย)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .base import Engine, OcrLine, register

# โควตาที่ประกาศไว้คือ 2 ครั้ง/วินาที และ 20 ครั้ง/นาที
# ตัวหลังเข้มกว่า จึงเว้นระยะ 3 วินาทีต่อครั้งเพื่อไม่ให้โดนปฏิเสธ
MIN_INTERVAL_SECONDS = 3.1

# ไม่ต้องย่อภาพลงมากเท่ารุ่นที่รันในเครื่อง เพราะไม่ติดข้อจำกัด VRAM
TARGET_IMAGE_DIM = 1800

_throttle = threading.Lock()
_last_call = 0.0


def _wait_turn() -> None:
    """เว้นระยะระหว่างการเรียกให้อยู่ในโควตา"""
    global _last_call
    with _throttle:
        gap = time.monotonic() - _last_call
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        _last_call = time.monotonic()


class TyphoonApi(Engine):
    name = "typhoon-api"
    label = "Typhoon OCR (API)"
    needs_gpu = False

    model = "typhoon-ocr"  # 1.5 รุ่น 2B — ตัวที่ผู้พัฒนาแนะนำ
    task_type = "v1.5"

    def available(self) -> tuple[bool, str]:
        try:
            import typhoon_ocr  # noqa: F401
        except ImportError as exc:
            return False, f"ยังไม่ได้ติดตั้ง typhoon-ocr ({exc})"
        if not (
            os.getenv("TYPHOON_OCR_API_KEY") or os.getenv("TYPHOON_API_KEY")
        ):
            return False, "ยังไม่ได้ตั้งตัวแปรแวดล้อม TYPHOON_OCR_API_KEY"
        return True, ""

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        from typhoon_ocr import ocr_document

        _wait_turn()
        started = time.perf_counter()
        text = ocr_document(
            pdf_or_image_path=str(image_path),
            task_type=self.task_type,
            target_image_dim=TARGET_IMAGE_DIM,
            model=self.model,
        )
        core_ms = (time.perf_counter() - started) * 1000

        # API คืน markdown ตัดสัญลักษณ์จัดรูปแบบออกให้เทียบกับ engine อื่นได้
        # ต้องห่อเป็น OcrLine ไม่ใช่ str เปล่า ๆ — store.from_result() เรียก ln.text
        lines = [
            OcrLine(text=stripped)
            for raw in (text or "").splitlines()
            if (stripped := _strip_markdown(raw))
        ]
        return lines, core_ms


def _strip_markdown(line: str) -> str:
    """ตัดสัญลักษณ์ markdown ที่ API ใส่มา ให้เหลือข้อความเปล่า"""
    text = line.strip()
    if not text or set(text) <= set("-|= "):  # เส้นคั่นและเส้นตาราง
        return ""
    text = text.lstrip("#").strip()
    text = text.replace("**", "").replace("__", "")
    if text.startswith("|") and text.endswith("|"):  # แถวตาราง
        text = " ".join(c.strip() for c in text.strip("|").split("|") if c.strip())
    return text.strip()


register(TyphoonApi())
