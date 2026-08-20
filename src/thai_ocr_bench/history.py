"""ประวัติการรันแต่ละรอบ — ตอบว่า "รอบนั้นสแกนอะไรไปบ้าง ได้อะไรกลับมา"

ทำไมต้องมีไฟล์นี้แยกจาก progress.py กับ store.py
    progress.py  เก็บสถานะรอบที่กำลังรัน เขียนทับตัวเองตลอด พอจบรอบก็หายไปกับรอบถัดไป
    store.py     เก็บผล OCR ล่าสุดต่อ (engine, หน้า) ไม่รู้ว่าผลนั้นมาจากรอบไหน
    ทั้งสองตัวจึงตอบไม่ได้ว่ารอบที่แล้วรันอะไร ใช้เวลาเท่าไร ได้กี่บรรทัด

เลือก JSONL เพราะเป็นการเขียนต่อท้ายล้วน ไม่ต้องอ่านของเก่าขึ้นมาทั้งก้อน
แล้วเขียนกลับ ซึ่งถ้าโปรแกรมตายกลางคันจะทำให้ไฟล์เดิมพังไปด้วย
บรรทัดที่พังอ่านไม่ออกจะถูกข้ามทีละบรรทัด ไม่ลากทั้งไฟล์ล่ม
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import RESULTS_DIR, ensure_dirs

HISTORY_FILE = "run_history.jsonl"


def _path():
    ensure_dirs()
    return RESULTS_DIR / HISTORY_FILE


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(record: dict[str, Any]) -> None:
    """ต่อท้ายหนึ่งรอบ — เรียกตอนจบรอบเสมอแม้รอบนั้นจะพังกลางคัน"""
    with _path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load(limit: int | None = None) -> list[dict[str, Any]]:
    """คืนประวัติเรียงจากรอบล่าสุดไปเก่าสุด"""
    path = _path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # บรรทัดพัง (เช่นเขียนค้างตอนไฟดับ) ข้ามไปอ่านบรรทัดอื่นต่อ
    rows.reverse()
    return rows[:limit] if limit else rows


def summarize(record: dict[str, Any]) -> str:
    """สรุปหนึ่งรอบเป็นข้อความบรรทัดเดียว ใช้ตอนแสดงในรายการ"""
    engines = record.get("engines", [])
    ran = [e for e in engines if not e.get("skipped")]
    lines = sum(e.get("lines", 0) for e in ran)
    fails = sum(e.get("failures", 0) for e in ran)
    note = f" · {fails} หน้าพัง" if fails else ""
    return (
        f"{len(ran)} engine × {record.get('pages', 0)} หน้า · "
        f"{lines:,} บรรทัด · {record.get('duration_s', 0) / 60:.1f} นาที{note}"
    )
