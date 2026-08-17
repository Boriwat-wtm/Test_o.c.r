"""สถานะการรัน เพื่อให้หน้าเว็บรู้ว่าตัวรันไปถึงไหนแล้ว

ตัวรันกับหน้าเว็บเป็นสองโปรเซสแยกกัน จึงคุยกันผ่านไฟล์
ตัวรันเขียนทับทุกครั้งที่อ่านหน้าเสร็จ หน้าเว็บอ่านแล้วคิดเปอร์เซ็นต์เอง

ถ้าไฟล์นี้ไม่มีหรือเก่าเกินไป หน้าเว็บจะเดาความคืบหน้าจากจำนวนผลที่เก็บได้แทน
เพื่อให้ยังใช้งานได้กับการรันที่เริ่มไปก่อนมีระบบนี้
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .config import RESULTS_DIR, ensure_dirs

STATUS_FILE = "run_status.json"

# ถ้าไม่มีการอัปเดตเกินเวลานี้ ถือว่าตัวรันหยุดไปแล้ว
# ตั้งเผื่อไว้กว้างเพราะ Typhoon ใช้เวลาต่อหน้าเกือบสองนาทีได้
STALE_SECONDS = 300


@dataclass
class RunStatus:
    engines: list[str] = field(default_factory=list)  # ตามลำดับที่จะรัน
    done_engines: list[str] = field(default_factory=list)
    current_engine: str | None = None
    pages_total: int = 0  # จำนวนหน้าต่อ engine ในรอบนี้
    pages_done: int = 0  # ของ engine ที่กำลังรัน
    current_page: str | None = None
    last_seconds: float | None = None  # เวลาที่ใช้กับหน้าล่าสุด
    failures: int = 0
    finished: bool = False
    started_at: str = ""
    updated_at: str = ""

    @property
    def overall_fraction(self) -> float:
        """ความคืบหน้ารวมทุก engine 0.0-1.0"""
        total = max(1, len(self.engines) * max(1, self.pages_total))
        done = len(self.done_engines) * max(1, self.pages_total) + self.pages_done
        return min(1.0, done / total)

    @property
    def engine_fraction(self) -> float:
        if not self.pages_total:
            return 0.0
        return min(1.0, self.pages_done / self.pages_total)

    @property
    def age_seconds(self) -> float | None:
        if not self.updated_at:
            return None
        try:
            stamp = datetime.fromisoformat(self.updated_at)
        except ValueError:
            return None
        return (datetime.now(timezone.utc) - stamp).total_seconds()

    @property
    def stale(self) -> bool:
        age = self.age_seconds
        return age is not None and age > STALE_SECONDS

    @property
    def running(self) -> bool:
        return not self.finished and not self.stale

    def eta_seconds(self) -> float | None:
        """เวลาที่เหลือโดยประมาณ คิดจากเวลาต่อหน้าของ engine ที่กำลังรัน

        ประมาณหยาบ ๆ เพราะแต่ละ engine เร็วช้าไม่เท่ากันมาก
        (Tesseract 5 วินาที ส่วน Typhoon 84 วินาที)
        """
        if self.finished or self.last_seconds is None:
            return None
        remaining_here = max(0, self.pages_total - self.pages_done)
        remaining_engines = max(
            0, len(self.engines) - len(self.done_engines) - 1
        )
        return self.last_seconds * (
            remaining_here + remaining_engines * self.pages_total
        )


def _path():
    ensure_dirs()
    return RESULTS_DIR / STATUS_FILE


def save(status: RunStatus) -> None:
    status.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _path().write_text(
        json.dumps(asdict(status), ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load() -> RunStatus | None:
    path = _path()
    if not path.exists():
        return None
    try:
        return RunStatus(**json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError):
        return None


def clear() -> None:
    path = _path()
    if path.exists():
        path.unlink()
