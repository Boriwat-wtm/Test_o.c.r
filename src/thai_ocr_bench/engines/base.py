"""อินเทอร์เฟซกลางของ OCR ทุกตัว

กติกาเดียวที่ทุก engine ต้องทำตาม: รับ "ภาพ" เข้าไปเท่านั้น ห้ามรับ PDF
เพราะบาง engine จะไปดึงข้อความจาก text layer แทนที่จะอ่านภาพ
แล้วได้คะแนนเต็มโดยไม่ได้ทดสอบอะไรเลย

การเพิ่ม engine ใหม่: สร้างคลาสสืบทอด Engine แล้ว register ไว้ท้ายไฟล์ของตัวเอง
ไม่ต้องแก้โค้ดวัดผลหรือหน้าเว็บ
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OcrLine:
    text: str
    confidence: float | None = None
    # กรอบในหน่วยพิกเซลของภาพ (x, y, กว้าง, สูง) ใช้ให้หน้าเว็บชี้ตำแหน่งได้
    box: tuple[int, int, int, int] | None = None


@dataclass
class OcrResult:
    engine: str
    page_id: str
    lines: list[OcrLine] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def ok(self) -> bool:
        return self.error is None


class Engine:
    """คลาสแม่ของทุก engine"""

    name: str = "base"
    label: str = "Base"
    needs_gpu: bool = False

    def available(self) -> tuple[bool, str]:
        """พร้อมใช้งานไหม คืน (พร้อม, เหตุผลถ้าไม่พร้อม)"""
        raise NotImplementedError

    def _run(self, image_path: Path) -> list[OcrLine]:
        raise NotImplementedError

    def run(self, image_path: Path, page_id: str) -> OcrResult:
        """เรียก _run พร้อมจับเวลาและดักข้อผิดพลาด

        engine ตัวหนึ่งพังต้องไม่ทำให้ทั้ง benchmark หยุด — บันทึก error ไว้
        แล้วให้ตัวอื่นรันต่อ หน้าเว็บจะแสดงว่าตัวนี้พังที่หน้าไหน
        """
        started = time.perf_counter()
        try:
            lines = self._run(image_path)
            error = None
        except Exception as exc:  # noqa: BLE001 — ตั้งใจดักทุกอย่าง
            lines, error = [], f"{type(exc).__name__}: {exc}"
        return OcrResult(
            engine=self.name,
            page_id=page_id,
            lines=lines,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=error,
        )


_REGISTRY: dict[str, Engine] = {}


def register(engine: Engine) -> Engine:
    _REGISTRY[engine.name] = engine
    return engine


def get_engines(names: list[str] | None = None) -> list[Engine]:
    """คืน engine ตามชื่อที่ขอ หรือทั้งหมดถ้าไม่ระบุ"""
    load_all()
    if names is None:
        return list(_REGISTRY.values())
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        raise KeyError(f"ไม่รู้จัก engine: {', '.join(missing)}")
    return [_REGISTRY[n] for n in names]


def load_all() -> None:
    """import ทุกโมดูล engine เพื่อให้ตัวเองลงทะเบียน

    ตัวที่ import ไม่ผ่าน (ยังไม่ได้ติดตั้ง) จะถูกข้ามเงียบ ๆ
    แล้วไปโผล่ในรายงานว่า "ยังไม่พร้อมใช้" แทน
    """
    from importlib import import_module

    for module in ("tesseract_tha", "easyocr_th", "paddle_th"):
        try:
            import_module(f".{module}", package=__package__)
        except Exception:  # noqa: BLE001, S110
            pass
