"""บันทึกเวอร์ชันของทุกอย่างที่ใช้รัน เก็บไปพร้อมผลลัพธ์

ถ้าไม่บันทึกไว้ พอกลับมาดูผลอีกสามเดือนจะไม่รู้ว่าตัวเลขมาจากรุ่นไหน
และเทียบกับผลรอบใหม่ไม่ได้เลย รายงานทุกฉบับจึงต้องแนบข้อมูลนี้
"""

from __future__ import annotations

import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version

from .config import TESSERACT_EXE

TRACKED_PACKAGES = (
    "pytesseract",
    "paddleocr",
    "paddlepaddle",
    "rapidocr",
    "easyocr",
    "surya-ocr",
    "typhoon-ocr",
    "torch",
    "transformers",
    "onnxruntime",
    "pymupdf",
    "rapidfuzz",
)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def tesseract_version() -> str | None:
    if not TESSERACT_EXE.exists():
        return None
    try:
        out = subprocess.run(
            [str(TESSERACT_EXE), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        first = (out.stdout or out.stderr).splitlines()[0]
        return first.replace("tesseract", "").strip()
    except Exception:  # noqa: BLE001
        return None


def gpu_info() -> str | None:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        line = out.stdout.strip().splitlines()
        return line[0] if line else None
    except Exception:  # noqa: BLE001
        return None


def snapshot() -> dict[str, str | None]:
    """ภาพนิ่งของสภาพแวดล้อมตอนรัน"""
    data: dict[str, str | None] = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "tesseract": tesseract_version(),
        "gpu": gpu_info(),
    }
    for name in TRACKED_PACKAGES:
        data[name] = _package_version(name)
    return data


def format_snapshot(data: dict[str, str | None] | None = None) -> str:
    data = data or snapshot()
    width = max(len(k) for k in data)
    lines = [
        f"  {k:<{width}}  {v}" for k, v in data.items() if v is not None
    ]
    missing = [k for k, v in data.items() if v is None]
    if missing:
        lines.append(f"  (ยังไม่ได้ติดตั้ง: {', '.join(missing)})")
    return "\n".join(lines)
