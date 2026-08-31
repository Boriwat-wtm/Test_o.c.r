"""เทสต์การส่งออก markdown — ความเสี่ยงคือ "กินงานที่คนแก้ไปแล้ว"

ไฟล์นี้เป็นทางเดียวที่งานแก้ด้วยมือของผู้ใช้ถูกเก็บไว้ ถ้า build() ไปทับ
ของที่บันทึกแล้ว งานที่นั่งแก้มาทั้งวันหายทันที
เทสต์จึงเน้นสองเรื่อง: ต้องไม่แปลงสิ่งที่ engine อ่านมา และของที่แก้แล้วต้องไม่ถูกทับ
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
        md = markdown_out.build("เอกสาร", "typhoon-api-num", PAGES)
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


class TestPageEdits:
    """แก้ทีละหน้าจากแท็บเปรียบเทียบ แล้วต้องไม่หายตอนส่งออกทั้งเอกสาร"""

    def test_edited_page_replaces_raw_in_the_document_export(
        self, tmp_path, monkeypatch
    ):
        """โจทย์หลัก — ถ้า build() ไม่หยิบของที่แก้ไว้ งานที่แก้ทีละหน้าหายหมด"""
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.save_page("doc1_p001", "e", "## แก้แล้ว\nบรรทัดที่แก้")
        md = markdown_out.build("เอกสาร", "e", PAGES)
        assert "## แก้แล้ว" in md
        assert "## กรมทะเบียนที่ดิน" not in md  # ผลดิบของหน้านั้นต้องถูกแทนที่
        assert "มาตรา ๙  ภายใต้บังคับกฎหมาย" in md  # หน้าที่ไม่ได้แก้ยังใช้ผลดิบ

    def test_header_counts_how_many_pages_were_edited(self, tmp_path, monkeypatch):
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.save_page("doc1_p001", "e", "แก้แล้ว")
        assert "แก้ด้วยมือแล้ว 1 หน้า" in markdown_out.build("เอกสาร", "e", PAGES)

    def test_edits_are_kept_per_engine(self, tmp_path, monkeypatch):
        """แก้บนฐานของ engine ไหน ต้องผูกกับตัวนั้น ไม่ปนกับตัวอื่น"""
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.save_page("doc1_p001", "engine-a", "ของ a")
        assert markdown_out.load_page("doc1_p001", "engine-b") is None

    def test_clear_page_falls_back_to_raw(self, tmp_path, monkeypatch):
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.save_page("doc1_p001", "e", "แก้แล้ว")
        markdown_out.clear_page("doc1_p001", "e")
        assert markdown_out.load_page("doc1_p001", "e") is None
        assert "## กรมทะเบียนที่ดิน" in markdown_out.build("เอกสาร", "e", PAGES)

    def test_clearing_a_page_that_was_never_edited_is_not_an_error(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path)
        markdown_out.clear_page("ไม่เคยแก้", "e")  # ต้องไม่โยน exception


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
