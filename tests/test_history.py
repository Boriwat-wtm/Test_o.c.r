"""เทสต์ประวัติการรัน — ต่อท้ายอย่างเดียว ห้ามเขียนทับของเก่า

ไฟล์ .jsonl สองไฟล์นี้เป็นบันทึกเดียวที่บอกว่าเคยรันอะไรไปแล้วบ้าง
ถ้า append ไปทับของเดิม ประวัติที่สะสมมาหายถาวร กู้ไม่ได้

อีกเรื่องที่ต้องคุมคือความทนต่อไฟล์พัง — โปรแกรมถูกฆ่ากลางคันตอนเขียน
บรรทัดสุดท้ายได้เสมอ (Ctrl+C ระหว่างรัน หรือไฟดับ) บรรทัดที่พังต้องไม่
ทำให้อ่านประวัติทั้งไฟล์ไม่ได้
"""

from __future__ import annotations

import pytest

from thai_ocr_bench import history


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_path", lambda: tmp_path / history.HISTORY_FILE)
    monkeypatch.setattr(
        history, "_page_path", lambda: tmp_path / history.PAGE_HISTORY_FILE
    )


class TestRunHistory:
    def test_เรียงจากรอบล่าสุดไปเก่าสุด(self):
        for i in range(3):
            history.append({"n": i})
        assert [r["n"] for r in history.load()] == [2, 1, 0]

    def test_ต่อท้ายไม่ทับของเก่า(self):
        history.append({"n": 0})
        history.append({"n": 1})
        assert len(history.load()) == 2

    def test_limit_ตัดเอาเฉพาะรอบล่าสุด(self):
        for i in range(5):
            history.append({"n": i})
        assert [r["n"] for r in history.load(limit=2)] == [4, 3]

    def test_ยังไม่มีไฟล์คืนลิสต์ว่างไม่ใช่พัง(self):
        assert history.load() == []

    def test_บรรทัดพังไม่ทำให้อ่านทั้งไฟล์ไม่ได้(self, tmp_path):
        """เคสจริง: โปรแกรมถูกฆ่าตอนเขียนบรรทัดสุดท้ายค้างครึ่งบรรทัด"""
        history.append({"n": 0})
        path = tmp_path / history.HISTORY_FILE
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"n": 1, ครึ่ง\n')
        history.append({"n": 2})
        assert [r["n"] for r in history.load()] == [2, 0]

    def test_บรรทัดว่างถูกข้าม(self):
        history.append({"n": 0})
        (history._path()).open("a", encoding="utf-8").write("\n\n")
        assert len(history.load()) == 1


class TestPageHistory:
    def add(self, run: str, page_id: str, lines: list[str]) -> None:
        history.append_page(run, "e", page_id, ok=True, ms=1.0, lines=lines)

    def test_เก็บแยกตามหน้า(self):
        self.add("r1", "p1", ["ก"])
        self.add("r1", "p2", ["ข"])
        assert len(history.load_page("p1")) == 1
        assert history.load_page("ไม่มีหน้านี้") == []

    def test_อ่านหน้าเดิมซ้ำเก็บครบทุกรอบ(self):
        """ต้องเห็นได้ว่าอ่านรอบก่อนได้อะไร เทียบกับรอบนี้"""
        self.add("r1", "p1", ["รอบแรก"])
        self.add("r2", "p1", ["รอบสอง"])
        rows = history.load_page("p1")
        assert [r["lines"] for r in rows] == [["รอบสอง"], ["รอบแรก"]]

    def test_เก็บข้อความไว้ด้วยไม่ใช่แค่จำนวนบรรทัด(self):
        """บรรทัดเท่ากันแต่เนื้อหาคนละเรื่องก็เป็นไปได้ ต้องเทียบเนื้อหาได้"""
        self.add("r1", "p1", ["มาตรา ๙"])
        assert history.load_page("p1")[0]["lines"] == ["มาตรา ๙"]

    def test_กรองหยาบด้วย_page_id_ต้องไม่หยิบหน้าอื่นมาปน(self):
        """load_page กรองด้วย `page_id in line` ก่อน parse — ชื่อที่เป็นส่วนหนึ่ง
        ของอีกชื่อจึงผ่านตัวกรองหยาบมาได้ ต้องถูกคัดออกตอนเทียบจริง"""
        self.add("r1", "doc1_p1", ["ก"])
        self.add("r1", "doc1_p10", ["ข"])
        assert len(history.load_page("doc1_p1")) == 1


class TestRunOrder:
    def test_ให้เลขรอบตามลำดับเวลา(self):
        """คีย์คือ started_at ไม่ใช่ชื่อรอบ — รอบแรกสุดตามเวลาได้เลข 1"""
        for stamp in ("2026-01-03", "2026-01-01", "2026-01-02"):
            history.append({"started_at": stamp})
        assert history.run_order() == {
            "2026-01-01": 1,
            "2026-01-02": 2,
            "2026-01-03": 3,
        }

    def test_รอบที่ไม่มีเวลาเริ่มถูกข้าม(self):
        history.append({"started_at": "2026-01-01"})
        history.append({})
        assert history.run_order() == {"2026-01-01": 1}
