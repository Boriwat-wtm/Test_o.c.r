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
import re
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


# Typhoon v1.5 ครอบส่วนที่รู้ว่าเป็นโครงสร้างหน้าไว้ในแท็ก เช่น
#   <page_number>- ๘ -</page_number>
# ต้องถอดแท็กออกแต่เก็บข้อความข้างในไว้ เพราะเลขหน้าอยู่ในเฉลยด้วย
# ถ้าปล่อยแท็กติดไป จะถูกนับเป็นตัวอักษรที่อ่านผิด ๒๖ ตัวต่อหน้า
# ซึ่งบนหน้าสั้น ๆ ดันค่า CER จาก ๐% ขึ้นไปเกือบ ๑๕%
_TAG = re.compile(r"</?[A-Za-z_][A-Za-z0-9_]*>")


def _strip_markdown(line: str) -> str:
    """ตัดสัญลักษณ์ markdown และแท็กโครงสร้างที่ API ใส่มา ให้เหลือข้อความเปล่า"""
    text = _TAG.sub("", line).strip()
    if not text or set(text) <= set("-|= "):  # เส้นคั่นและเส้นตาราง
        return ""
    text = text.lstrip("#").strip()
    text = text.replace("**", "").replace("__", "")
    if text.startswith("|") and text.endswith("|"):  # แถวตาราง
        text = " ".join(c.strip() for c in text.strip("|").split("|") if c.strip())
    return text.strip()


class TyphoonApiThaiNum(Engine):
    """Typhoon ตัวเดิม แต่กำชับเรื่องเลขไทยเพิ่มในคำสั่ง

    ที่มา: วัดผลชุด ๑๒ หน้าแล้วพบว่าความผิดที่เหลือของ Typhoon เกือบทั้งหมด
    เป็นเรื่องเดียว — เลขเชิงอรรถที่เป็นเลขไทยยกกำลัง (๑๐ ๑๑ ๑๖)
    ถูกคืนออกมาเป็นเลขอารบิกยกกำลัง (¹⁰ ¹¹ ¹⁶) ๙ จุดจาก ๒๐ จุด
    ค่ายังถูกแต่เสียความเป็นเลขไทย ซึ่งเป็นสิ่งที่งานนี้วัดโดยตรง

    แยกเป็นคนละ engine ไม่ใช่แก้ตัวเดิม เพื่อให้เทียบกันตรง ๆ ได้ว่า
    การกำชับช่วยจริงไหม ไม่ใช่เปลี่ยนของเดิมแล้วอ้างว่าดีขึ้นโดยไม่มีตัวเทียบ

    engine อื่นไม่มีช่องให้สั่งแบบนี้ ตอนสรุปผลจึงต้องระบุไว้ด้วยว่า
    ตัวนี้ได้คำใบ้เพิ่ม ไม่ใช่ค่าเริ่มต้นที่แกะกล่องมาแล้วได้เลย
    """

    name = "typhoon-api-num"
    label = "Typhoon OCR (API + กำชับเลขไทย)"
    needs_gpu = False

    model = TyphoonApi.model
    task_type = TyphoonApi.task_type

    HINT = (
        "\n- Thai numerals: Keep Thai digits (๐๑๒๓๔๕๖๗๘๙) exactly as they appear. "
        "Never convert them to Arabic digits (0-9) or to superscript characters "
        "(⁰¹²³⁴⁵⁶⁷⁸⁹). This applies to footnote markers and superscripts too — "
        "if the mark in the image is a Thai digit, output a Thai digit."
    )

    def available(self) -> tuple[bool, str]:
        return TyphoonApi().available()

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        from openai import OpenAI
        from typhoon_ocr.ocr_utils import prepare_ocr_messages

        messages = prepare_ocr_messages(
            pdf_or_image_path=str(image_path),
            task_type=self.task_type,
            target_image_dim=TARGET_IMAGE_DIM,
        )
        # ต่อคำกำชับท้ายกฎการจัดรูปแบบเดิม ไม่ทับของเดิมทิ้ง
        for part in messages[-1]["content"]:
            if part.get("type") == "text":
                part["text"] = part["text"].rstrip() + self.HINT
                break

        client = OpenAI(
            base_url=os.getenv("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1"),
            api_key=os.getenv("TYPHOON_OCR_API_KEY") or os.getenv("TYPHOON_API_KEY"),
        )
        _wait_turn()
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=16384,
            # ค่าเดียวกับที่ ocr_document() ใช้กับ v1.5 เพื่อให้เทียบกันได้
            extra_body={"repetition_penalty": 1.1, "temperature": 0.1, "top_p": 0.6},
        )
        core_ms = (time.perf_counter() - started) * 1000

        text = response.choices[0].message.content
        lines = [
            OcrLine(text=stripped)
            for raw in (text or "").splitlines()
            if (stripped := _strip_markdown(raw))
        ]
        return lines, core_ms


register(TyphoonApi())
register(TyphoonApiThaiNum())
