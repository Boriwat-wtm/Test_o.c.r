"""เครื่องมือเปรียบเทียบความแม่นของ OCR บนเอกสารภาษาไทย

โมดูลนี้ตั้งที่เก็บโมเดลใหม่ทั้งหมดตั้งแต่ตอน import

ปกติแต่ละไลบรารีจะโหลดโมเดลลงโฟลเดอร์บ้านของผู้ใช้บนไดรฟ์ C กระจายกันคนละที่
(.paddlex, .cache/huggingface, .EasyOCR, .cache/torch) รวมกันหลายกิกะไบต์
และหายาก เราจึงย้ายมารวมไว้ที่ vendor/cache/ ในโปรเจกต์ ลบทีเดียวจบ

ต้องตั้งก่อน import ไลบรารีพวกนั้น จึงวางไว้ในไฟล์นี้ซึ่งทำงานก่อนเสมอ
"""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

_ROOT = Path(__file__).resolve().parents[2]
# ที่เก็บโมเดลทั้งหมด — ลบโฟลเดอร์นี้ทิ้งได้เลยถ้าอยากเคลียร์พื้นที่
_CACHE = _ROOT / "vendor" / "cache"

# ตัวแปร -> โฟลเดอร์ย่อย  (ยืนยันชื่อตัวแปรจากซอร์สของแต่ละไลบรารีแล้ว)
_CACHE_VARS = {
    "PADDLE_PDX_CACHE_HOME": "paddlex",  # paddlex/utils/cache.py
    "HF_HOME": "huggingface",  # Typhoon, TrOCR
    "EASYOCR_MODULE_PATH": "easyocr",
    "TORCH_HOME": "torch",
    # Surya ไม่เคารพ HF_HOME มันใช้ค่าของตัวเองซึ่งชี้ไป
    # C:\Users\...\AppData\Local\datalab\ โดยปริยาย (surya/settings.py)
    "MODEL_CACHE_DIR": "surya",
    "XDG_CACHE_HOME": "xdg",  # ตัวสำรองของไลบรารีที่เคารพมาตรฐานนี้
}


def _load_dotenv(path: "Path | None" = None) -> None:
    """อ่านค่าจากไฟล์ .env ที่รากโปรเจกต์ ถ้ามี

    เขียนเองแทนการพึ่ง python-dotenv เพราะต้องการแค่รูปแบบ KEY=VALUE ธรรมดา
    และอยากคุมพฤติกรรมสองข้อนี้เอง
      - ตัวแปรที่ตั้งไว้ในระบบอยู่แล้วต้องชนะค่าในไฟล์เสมอ (ใช้ setdefault)
      - ค่าว่างถือว่ายังไม่ได้ตั้ง ไม่ใช่ตั้งเป็นสตริงว่าง
        เพราะไฟล์ตัวอย่างมีบรรทัด KEY= ค้างไว้ ถ้าไม่กันไว้ engine จะรายงานว่า
        พร้อมใช้แล้วไปพังตอนเรียก API แทนที่จะบอกตั้งแต่แรกว่ายังไม่ได้ใส่คีย์
    """
    path = path or _ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            os.environ.setdefault(key, value)


_load_dotenv()


def _redirect_model_caches() -> None:
    """ชี้ที่เก็บโมเดลของทุกไลบรารีมาที่ vendor/cache/ ในโปรเจกต์

    ใช้ setdefault เพื่อไม่ทับค่าที่ผู้ใช้ตั้งเองไว้ก่อนแล้ว
    """
    for var, folder in _CACHE_VARS.items():
        target = _CACHE / folder
        if os.environ.get(var):
            continue
        target.mkdir(parents=True, exist_ok=True)
        os.environ[var] = str(target)


_redirect_model_caches()

