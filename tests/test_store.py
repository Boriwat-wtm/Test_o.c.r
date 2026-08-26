"""เทสต์ที่เก็บผล OCR — ความเสี่ยงคือ "ข้อมูลที่รันมาเป็นชั่วโมงหาย"

ไฟล์ ocr_results.json คือผลจากการรัน OCR ที่กินเวลารวมหลายชั่วโมงและกินโควตา
API ไปแล้ว ถ้า save/load ทำข้อมูลตกหล่นหรือ upsert ไปทับของเดิม ต้องรันใหม่หมด
เทสต์จึงเน้นสองเรื่อง: วนไป-กลับต้องได้ของเดิมครบ และเขียนหน้าใหม่ต้องไม่ลบหน้าเก่า

โมดูลนี้ไม่เคยมีเทสต์เลยทั้งที่เป็นตัวที่พังแล้วเสียหายที่สุดในโปรเจกต์
"""

from __future__ import annotations

import pytest

from thai_ocr_bench import store
from thai_ocr_bench.engines.base import OcrLine, OcrResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """กันไม่ให้เทสต์ไปเขียนทับ results/ ของจริงในเครื่อง"""
    monkeypatch.setattr(store, "RESULTS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(store, "_path", lambda: tmp_path / store.RESULTS_FILE)


def page(**kw) -> store.StoredPage:
    base = dict(
        lines=["บรรทัดหนึ่ง", "มาตรา ๙"],
        boxes=[[1, 2, 3, 4], None],
        confidences=[0.9, None],
        core_ms=12.5,
        elapsed_ms=20.0,
        read_at="2026-01-01T00:00:00+00:00",
    )
    return store.StoredPage(**{**base, "error": None, **kw})


class TestRoundTrip:
    def test_ทุกฟิลด์กลับมาครบหลังบันทึกแล้วอ่านใหม่(self):
        """ตกฟิลด์ไหนไปแปลว่าต้องรัน OCR ใหม่ทั้งชุดเพื่อเอากลับมา"""
        store.save({"e": {"p1": page()}}, {"versions": {"torch": "2.13"}})
        got = store.load()["e"]["p1"]
        assert got == page()
        assert store.load_meta() == {"versions": {"torch": "2.13"}}

    def test_กรอบที่เป็น_None_ต้องยังเป็น_None(self):
        """engine อย่าง Typhoon ไม่คืนพิกัด ถ้าแปลงเป็น [] หน้าเว็บจะชี้ตำแหน่งมั่ว"""
        store.save({"e": {"p1": page(boxes=[None, None])}})
        assert store.load()["e"]["p1"].boxes == [None, None]

    def test_หน้าที่พังเก็บ_error_ไว้ด้วย(self):
        store.save({"e": {"p1": page(lines=[], error="OOM")}})
        got = store.load()["e"]["p1"]
        assert got.error == "OOM"
        assert got.ok is False

    def test_ยังไม่มีไฟล์คืนค่าว่างไม่ใช่พัง(self):
        assert store.load() == {}
        assert store.load_meta() == {}


class TestUpsert:
    def test_เขียนหน้าใหม่ไม่ลบหน้าเก่า(self):
        """upsert เขียนทีละหน้าเพื่อให้ขัดจังหวะกลางทางได้ ต้องไม่กินของเดิม"""
        store.save({"e": {"p1": page()}})
        store.upsert("e", "p2", page(lines=["หน้าสอง"]))
        assert sorted(store.load()["e"]) == ["p1", "p2"]

    def test_เขียนทับหน้าเดิมได้(self):
        store.save({"e": {"p1": page()}})
        store.upsert("e", "p1", page(lines=["อ่านใหม่"]))
        assert store.load()["e"]["p1"].lines == ["อ่านใหม่"]

    def test_เพิ่ม_engine_ใหม่ไม่ลบ_engine_เดิม(self):
        store.save({"a": {"p1": page()}})
        store.upsert("b", "p1", page())
        assert sorted(store.load()) == ["a", "b"]

    def test_meta_ถูกรวมไม่ใช่เขียนทับทิ้ง(self):
        """เวอร์ชันที่บันทึกไว้ต้องไม่หายเมื่อ upsert ส่ง meta แค่บางส่วนมา"""
        store.save({"e": {"p1": page()}}, {"versions": {"torch": "2.13"}})
        store.upsert("e", "p2", page(), meta={"started_at": "2026-01-01"})
        assert store.load_meta() == {
            "versions": {"torch": "2.13"},
            "started_at": "2026-01-01",
        }


class TestFromResult:
    def test_แปลงผลดิบของ_engine_เป็นรูปที่เก็บได้(self):
        result = OcrResult(
            engine="e",
            page_id="p1",
            lines=[OcrLine(text="ก", confidence=0.8, box=(1, 2, 3, 4))],
            elapsed_ms=30.0,
            core_ms=25.0,
        )
        got = store.from_result(result)
        assert got.lines == ["ก"]
        assert got.boxes == [[1, 2, 3, 4]]
        assert got.confidences == [0.8]
        assert (got.core_ms, got.elapsed_ms) == (25.0, 30.0)
        assert got.read_at  # ต้องมีเวลากำกับเสมอ ไม่งั้นไล่ย้อนไม่ได้ว่าอ่านเมื่อไร

    def test_ไม่มี_core_ms_ให้ตกมาใช้_elapsed_ms(self):
        """engine ที่ไม่แยกเวลาส่วนที่ใช้จริง ต้องไม่ได้ core_ms เป็น None"""
        result = OcrResult(engine="e", page_id="p1", elapsed_ms=30.0)
        assert store.from_result(result).core_ms == 30.0
