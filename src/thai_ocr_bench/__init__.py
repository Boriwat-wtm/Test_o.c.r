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


def cache_root() -> Path:
    """ที่เก็บโมเดลทั้งหมด — ลบโฟลเดอร์นี้ทิ้งได้เลยถ้าอยากเคลียร์พื้นที่"""
    return _CACHE
