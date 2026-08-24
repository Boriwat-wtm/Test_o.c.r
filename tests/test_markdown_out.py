"""เทสต์การส่งออก markdown — ความเสี่ยงคือ "กินงานที่คนแก้ไปแล้ว"

ไฟล์นี้เป็นทางเดียวที่งานแก้ด้วยมือของผู้ใช้ถูกเก็บไว้ ถ้า build() ไปทับ
ของที่บันทึกแล้ว หรือ split_pages() คืนหน้าผิด งานที่นั่งแก้มาทั้งวันหายทันที
เทสต์จึงเน้นสองเรื่อง: ต้องไม่แปลงสิ่งที่ engine อ่านมา และต้องวนกลับได้ครบ
"""

from __future__ import annotations

import pytest

from thai_ocr_bench import markdown_out

PAGES = [
    (1, "doc1_p001", ["## กรมทะเบียนที่ดิน", "วันที่ ๒๐ เมษายน"]),
    (2, "doc1_p002", ["มาตรา ๙  ภายใต้บังคับกฎหมาย"]),
]


class TestBuild:
    def test_keeps_engine_markdown_untouched(self):
        """Typhoon คืนหัวข้อมาเป็น ## อยู่แล้ว ห้ามไปตัดหรือแปลงเพิ่ม"""
        md = markdown_out.build("เอกสาร", "typhoon-2b", PAGES)
        assert "## กรมทะเบียนที่ดิน" in md

    def test_page_markers_are_invisible_comments_not_headings(self):
        """ใช้ ## คั่นหน้าไม่ได้ จะชนกับหัวข้อที่ engine อ่านมาจากตัวเอกสารเอง"""
        md = markdown_out.build("เอกสาร", "e", PAGES)
        assert "<!-- หน้า 1 · doc1_p001 -->" in md
        assert "## หน้า" not in md

    def test_empty_page_is_marked_not_silently_dropped(self):
        md = markdown_out.build("เอกสาร", "e", [(1, "p1", [])])
        assert "*(ไม่มีข้อความ)*" in md
        assert "<!-- หน้า 1 · p1 -->" in md


class TestSplitPages:
    def test_round_trips_every_page(self):
        md = markdown_out.build("เอกสาร", "e", PAGES)
        assert markdown_out.split_pages(md) == {
            "doc1_p001": ["## กรมทะเบียนที่ดิน", "วันที่ ๒๐ เมษายน"],
            "doc1_p002": ["มาตรา ๙  ภายใต้บังคับกฎหมาย"],
        }

    def test_survives_hand_editing(self):
        """คนแก้แล้วต้องยังแยกหน้าได้ — นี่คือกรณีใช้งานหลักของฟังก์ชันนี้"""
        md = markdown_out.build("เอกสาร", "e", PAGES)
        edited = md.replace("วันที่ ๒๐ เมษายน", "วันที่ ๒๑ เมษายน\nเพิ่มบรรทัดใหม่")
        out = markdown_out.split_pages(edited)
        assert out["doc1_p001"] == [
            "## กรมทะเบียนที่ดิน",
            "วันที่ ๒๑ เมษายน",
            "เพิ่มบรรทัดใหม่",
        ]

    def test_header_block_is_not_mistaken_for_content(self):
        """หัวเรื่องกับคำอธิบายด้านบนไม่ใช่เนื้อหาของหน้าไหน ต้องไม่ติดมา"""
        md = markdown_out.build("เอกสาร", "e", PAGES)
        assert not any(
            "อ่านด้วย" in ln for lines in markdown_out.split_pages(md).values()
            for ln in lines
        )


class TestSaveLoad:
    def test_saved_version_wins_over_rebuilding(self, tmp_path, monkeypatch):
        """โจทย์หลักของโมดูลนี้ — ของที่คนแก้แล้วต้องไม่ถูกผลดิบทับ"""
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.save("เอกสาร", "e", "ฉบับที่คนแก้แล้ว")
        assert markdown_out.load("เอกสาร", "e") == "ฉบับที่คนแก้แล้ว"

    def test_load_returns_none_before_first_save(self, tmp_path, monkeypatch):
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        assert markdown_out.load("ยังไม่เคยบันทึก", "e") is None

    @pytest.mark.parametrize("name", ["ก/ข", "ก:ข", 'ก"ข', "ก|ข", "ก?ข", "ก*ข"])
    def test_illegal_windows_filename_characters_are_replaced(
        self, name, tmp_path, monkeypatch
    ):
        """ชื่อเอกสารมาจากชื่อไฟล์ PDF ซึ่งมีอักขระที่ Windows ห้ามใช้ได้"""
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        path = markdown_out.save(name, "e", "เนื้อหา")
        assert path.exists()
        assert markdown_out.load(name, "e") == "เนื้อหา"
