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

# ค่าเดียวกับที่ SDK ใช้ตอนเรียก ocr_document() — read_variants() ต้องเรียก API
# เองจึงต้องประกาศซ้ำตรงนี้ ถ้าค่าสองที่ไม่ตรงกันจะเทียบผลกันไม่ได้
API_BASE_URL = "https://api.opentyphoon.ai/v1"
MAX_TOKENS = 16384

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

    def _client(self):
        from openai import OpenAI

        return OpenAI(
            base_url=os.getenv("TYPHOON_BASE_URL", API_BASE_URL),
            api_key=os.getenv("TYPHOON_OCR_API_KEY") or os.getenv("TYPHOON_API_KEY"),
        )

    def _messages(self, image_path: Path) -> list:
        """ประกอบคำสั่งที่จะส่งให้ API — คลาสลูกแทรกคำกำชับเพิ่มได้ที่นี่

        แยกออกมาเพื่อให้ read_variants() ใช้ร่วมกับคลาสลูกได้ ถ้าประกอบ
        คำสั่งซ้ำในแต่ละเมธอด คลาสลูกจะได้คำสั่งคนละชุดกับตอน _run()
        แล้วผลอ่านซ้ำจะเทียบกับผลปกติไม่ได้
        """
        from typhoon_ocr.ocr_utils import prepare_ocr_messages

        return prepare_ocr_messages(
            pdf_or_image_path=str(image_path),
            task_type=self.task_type,
            target_image_dim=TARGET_IMAGE_DIM,
        )

    def read_variants(
        self, image_path: Path, *, n: int = 3, temperature: float = 0.3
    ) -> list[str]:
        """อ่านภาพเดิมซ้ำ n รอบแบบสุ่ม คืนข้อความทุกรอบ — ใช้ดู self-consistency

        temperature 0.3 มาจากการวัด ไม่ได้เดา — ลอง 0.1/0.3/0.6 กับหน้าที่มีเฉลย
          0.1  ข้ามได้ 11/15 บรรทัด แต่พลาดของผิดไป 5 (มั่นใจผิด อันตรายที่สุด)
          0.3  ข้ามได้ 6/15 พลาด 1 จับผิดได้ 88% เตือนเปล่า 22%
          0.6  จับได้ 100% แต่ต้องตรวจ 13/15 แทบไม่ประหยัดแรงคน
        ค่าเดิม 0.9 สูงเกินจนโมเดลพ่นของแย่กว่าที่ทำได้จริง กลายเป็นวัด
        ความไม่นิ่งที่เราสร้างขึ้นเอง ไม่ใช่ความลังเลตามธรรมชาติของมัน
        (วัดจากหน้าเดียว 15 บรรทัด กลุ่มตัวอย่างเล็ก ตัวเลขจะขยับเมื่อวัดเพิ่ม)

        ต้องเรียก API เองแทน ocr_document() เพราะ SDK ตรึง temperature=0.1
        กับ top_p=0.6 ไว้ตายตัวในตัวมัน (ocr_utils.py) ส่งค่าอื่นเข้าไปไม่ได้
        ซึ่งเกือบเป็น greedy จนอ่านซ้ำกี่รอบก็ได้คำตอบเดิม ใช้เช็กความมั่นใจไม่ได้

        ทำไมฝั่ง API ทำได้แค่วิธีนี้ วิธีเดียว
            confidence ระดับ token ทำไม่ได้ — ทดสอบแล้วเซิร์ฟเวอร์รับ
            logprobs=True ไปแบบไม่ error แต่คืน logprobs เป็น None เสมอ
            (ต่างจาก typhoon-2b ที่รันเองในเครื่องจึงอ่านค่าตอน generate ได้)

        กินโควตา n เท่าของการอ่านปกติ โควตาคือ 20 ครั้ง/นาที จึงควรใช้กับ
        ภาพครอปทีละบรรทัด (แบบ rescue.py) ไม่ใช่ทั้งหน้า
        """
        client = self._client()
        messages = self._messages(image_path)

        out: list[str] = []
        for _ in range(n):
            _wait_turn()
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=MAX_TOKENS,
                extra_body={
                    "repetition_penalty": 1.1,
                    "temperature": temperature,
                    "top_p": 0.95,
                },
            )
            text = (response.choices[0].message.content or "").strip()
            # ถอด markdown เหมือน _run() ไม่งั้นเทียบกันแล้วต่างเพราะสัญลักษณ์
            # จัดรูปแบบ ไม่ใช่เพราะอ่านได้ไม่เหมือนกันจริง
            cleaned = "\n".join(
                stripped
                for raw in text.splitlines()
                if (stripped := _strip_markdown(raw))
            )
            if cleaned:
                out.append(cleaned)
        return out

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

# ตัวหนา markdown ต้องมาเป็นคู่และมีเนื้อหาคั่นกลาง
#
# เดิมใช้ replace("**", "") ลบทุกตัวที่เจอ ซึ่งกินเครื่องหมายเชิงอรรถของเอกสารไปด้วย
# หน้าคำสั่งกรมที่ดินใช้ * กับ ** เป็นตัวโยงหมายเหตุสองอัน
#     *  (ที่ดินแบบ ๓๔) (ท.ด. ๓๔)
#    **  (ที่ดินแบบ ๓๕) คือ (ท.ด. ๓๕) เดิมซึ่งได้ยุบเลิก...
# ตัวเดียวรอด แต่สองตัวหายทั้งที่ Typhoon อ่านมาถูก แล้วถูกนับเป็นตัวอักษรที่ขาด
# เป็นความผิดพลาดแบบเดียวกับแท็ก <page_number> ที่เคยแก้ไปแล้ว
# คือลงโทษ engine ที่อ่านถูกเพราะขั้นตอนหลังบ้านของเราเอง
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)

# หัวข้อ markdown ต้องมีช่องว่างตามหลัง # เสมอ
# lstrip("#") เฉย ๆ จะกินกรณีที่ # เป็นอักขระจริงในเอกสาร
_HEAD = re.compile(r"^#{1,6}\s+")


def _strip_markdown(line: str) -> str:
    """ตัดสัญลักษณ์ markdown และแท็กโครงสร้างที่ API ใส่มา ให้เหลือข้อความเปล่า

    ตัดเฉพาะที่เป็นสัญลักษณ์จัดรูปแบบจริง ๆ ไม่ใช่ทุกตัวที่หน้าตาเหมือน
    เพราะเอกสารราชการใช้อักขระพวกนี้เป็นเนื้อหาด้วย
    """
    text = _TAG.sub("", line).strip()
    if not text or set(text) <= set("-|= "):  # เส้นคั่นและเส้นตาราง
        return ""
    text = _HEAD.sub("", text).strip()
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    if text.startswith("|") and text.endswith("|"):  # แถวตาราง
        text = " ".join(c.strip() for c in text.strip("|").split("|") if c.strip())
    return text.strip()


class TyphoonApiThaiNum(TyphoonApi):
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

    HINT = (
        "\n- Thai numerals: Keep Thai digits (๐๑๒๓๔๕๖๗๘๙) exactly as they appear. "
        "Never convert them to Arabic digits (0-9) or to superscript characters "
        "(⁰¹²³⁴⁵⁶⁷⁸⁹). This applies to footnote markers and superscripts too — "
        "if the mark in the image is a Thai digit, output a Thai digit."
    )

    def _messages(self, image_path: Path) -> list:
        """คำสั่งชุดเดียวกับตัวแม่ แต่ต่อคำกำชับเลขไทยท้ายกฎการจัดรูปแบบ

        อยู่ตรงนี้ที่เดียว ทั้ง _run() และ read_variants() จึงได้คำกำชับ
        เหมือนกัน ผลอ่านซ้ำแบบสุ่มจึงเทียบกับผลปกติได้จริง
        """
        messages = super()._messages(image_path)
        # ต่อท้ายของเดิม ไม่ทับทิ้ง
        for part in messages[-1]["content"]:
            if part.get("type") == "text":
                part["text"] = part["text"].rstrip() + self.HINT
                break
        return messages

    def _run(self, image_path: Path) -> tuple[list[OcrLine], float]:
        messages = self._messages(image_path)
        client = self._client()
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
