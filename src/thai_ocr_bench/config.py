"""ที่อยู่ของไฟล์ต่าง ๆ และค่าคงที่ที่ใช้ร่วมกันทั้งโปรเจกต์"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# เอกสารต้นฉบับอยู่นอกโปรเจกต์ ตั้งใจให้ไม่ถูก git แตะ
SOURCE_DIR = Path(
    os.environ.get("THAI_OCR_SOURCE_DIR", r"D:\Coding\Test OCR เอกสารทดสอบ")
)

DATA_DIR = ROOT / "data"
IMAGE_DIR = DATA_DIR / "images"
# ภาพชุดเดียวกันแต่ลบลายน้ำแล้ว เก็บแยกเพื่อให้เทียบผลกับชุดดิบได้
CLEAN_IMAGE_DIR = DATA_DIR / "cleaned"
TRUTH_DIR = DATA_DIR / "truth"
RESULTS_DIR = ROOT / "results"
VENDOR_DIR = ROOT / "vendor"
TESSDATA_DIR = VENDOR_DIR / "tessdata"

RENDER_DPI = 300

# Tesseract ติดตั้งแยกจาก Python จึงต้องรู้ที่อยู่ของตัว exe
TESSERACT_EXE = Path(
    os.environ.get("TESSERACT_EXE", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
)


CACHE_DIR = VENDOR_DIR / "cache"


def ensure_dirs() -> None:
    for d in (
        IMAGE_DIR,
        CLEAN_IMAGE_DIR,
        TRUTH_DIR,
        RESULTS_DIR,
        TESSDATA_DIR,
        CACHE_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
