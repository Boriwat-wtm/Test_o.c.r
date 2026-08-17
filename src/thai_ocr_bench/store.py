"""เก็บผลที่ OCR อ่านได้ลงดิสก์ แยกจากการวัดผลและหน้าเว็บ

แยกเป็นสองขั้นเพราะการรัน OCR กินเวลา 10-50 วินาทีต่อหน้า ถ้ารันในหน้าเว็บ
จะค้างและ timeout พอเก็บผลไว้แล้ว หน้าเว็บก็แค่อ่านไฟล์ ทำให้เปลี่ยนสูตร
การวัดผลแล้วดูผลใหม่ได้ทันทีโดยไม่ต้องรัน OCR ซ้ำ
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import RESULTS_DIR, ensure_dirs
from .engines.base import OcrResult

RESULTS_FILE = "ocr_results.json"


@dataclass
class StoredPage:
    lines: list[str] = field(default_factory=list)
    boxes: list[list[int] | None] = field(default_factory=list)
    confidences: list[float | None] = field(default_factory=list)
    core_ms: float = 0.0
    elapsed_ms: float = 0.0
    error: str | None = None
    read_at: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


def _path():
    ensure_dirs()
    return RESULTS_DIR / RESULTS_FILE


def load() -> dict[str, dict[str, StoredPage]]:
    """คืนผลในรูป {ชื่อ engine: {page_id: ผล}}"""
    path = _path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, StoredPage]] = {}
    for engine, pages in raw.get("engines", {}).items():
        out[engine] = {pid: StoredPage(**data) for pid, data in pages.items()}
    return out


def load_meta() -> dict:
    path = _path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("meta", {})


def save(
    results: dict[str, dict[str, StoredPage]],
    meta: dict | None = None,
) -> None:
    payload = {
        "meta": meta or {},
        "engines": {
            engine: {
                pid: {
                    "lines": p.lines,
                    "boxes": p.boxes,
                    "confidences": p.confidences,
                    "core_ms": p.core_ms,
                    "elapsed_ms": p.elapsed_ms,
                    "error": p.error,
                    "read_at": p.read_at,
                }
                for pid, p in pages.items()
            }
            for engine, pages in results.items()
        },
    }
    _path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def from_result(result: OcrResult) -> StoredPage:
    return StoredPage(
        lines=[ln.text for ln in result.lines],
        boxes=[list(ln.box) if ln.box else None for ln in result.lines],
        confidences=[ln.confidence for ln in result.lines],
        core_ms=result.core_ms or result.elapsed_ms,
        elapsed_ms=result.elapsed_ms,
        error=result.error,
        read_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def upsert(
    engine: str,
    page_id: str,
    page: StoredPage,
    meta: dict | None = None,
) -> None:
    """บันทึกผลของหน้าเดียว เขียนทับทีละหน้าเพื่อให้ขัดจังหวะกลางทางได้"""
    results = load()
    results.setdefault(engine, {})[page_id] = page
    existing = load_meta()
    if meta:
        existing.update(meta)
    save(results, existing)
