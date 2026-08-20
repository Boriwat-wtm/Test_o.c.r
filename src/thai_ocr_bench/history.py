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

# ผลรายหน้าต่อรอบ แยกไฟล์จากสรุปรอบเพราะโตคนละอัตรากันมาก
# สรุปรอบโตทีละบรรทัดต่อรอบ ส่วนตัวนี้โตทีละ (engine x หน้า) ต่อรอบ
# ปนกันจะทำให้หน้าที่แค่อยากดูรายการรอบต้องอ่านข้อความ OCR ทั้งหมดขึ้นมาด้วย
PAGE_HISTORY_FILE = "page_history.jsonl"


def _path():
    ensure_dirs()
    return RESULTS_DIR / HISTORY_FILE


def _page_path():
    ensure_dirs()
    return RESULTS_DIR / PAGE_HISTORY_FILE


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


def append_page(
    run: str, engine: str, page_id: str, *, ok: bool, ms: float, lines: list[str],
    error: str | None = None,
) -> None:
    """บันทึกผลของหนึ่งหน้าในหนึ่งรอบ

    เก็บข้อความที่อ่านได้ไว้ด้วย ไม่ใช่แค่จำนวนบรรทัด เพราะจุดประสงค์คือ
    เอามาเทียบว่ารอบนี้อ่านได้ต่างจากรอบก่อนตรงไหน ซึ่งดูจากตัวเลขอย่างเดียวไม่ได้
    (บรรทัดเท่ากันแต่เนื้อหาคนละเรื่องก็เป็นไปได้)
    """
    with _page_path().open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "run": run,
                    "engine": engine,
                    "page_id": page_id,
                    "ok": ok,
                    "ms": ms,
                    "lines": lines,
                    "error": error,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def load_page(page_id: str) -> list[dict[str, Any]]:
    """ทุกครั้งที่หน้านี้เคยถูกอ่าน เรียงจากรอบล่าสุดไปเก่าสุด

    อ่านทั้งไฟล์แล้วกรอง เพราะ JSONL ไม่มีดัชนี ถ้าไฟล์โตจนช้า
    ค่อยย้ายไปเก็บแยกรายหน้าทีหลัง ตอนนี้ยังคุ้มกว่าความซับซ้อนที่เพิ่ม
    """
    path = _page_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or page_id not in line:  # กรองหยาบก่อน เลี่ยงการ parse ทุกบรรทัด
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("page_id") == page_id:
            rows.append(row)
    rows.reverse()
    return rows


def run_order() -> dict[str, int]:
    """แปลงเวลาเริ่มของแต่ละรอบเป็นเลขรอบ (รอบที่ 1 = รอบแรกสุดตามเวลา)"""
    stamps = sorted({r.get("started_at", "") for r in load() if r.get("started_at")})
    return {s: i + 1 for i, s in enumerate(stamps)}


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
