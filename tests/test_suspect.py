"""เทสต์ตัวหาจุดน่าสงสัย — ตัวนี้ทำงานตอนไม่มีเฉลย จึงตรวจตัวเองไม่ได้

ความเสี่ยงของโมดูลนี้คือ "เตือนผิด" มากกว่า "จับไม่ได้"
ถ้าเตือนทุกบรรทัดจนคนเลิกอ่าน เครื่องมือก็ไร้ค่าทั้งที่ตัวเลข recall สวย
เทสต์จึงคุมสองด้านเสมอ: ต้องจับของจริงได้ และต้องเงียบเมื่อไม่มีอะไรผิด
"""

from __future__ import annotations

from thai_ocr_bench.suspect import (
    build_grid,
    cross_engine_findings,
    find_in_line,
    pick_grid,
    rule_findings,
    scan_page,
    section_findings_by_document,
    section_length_outliers,
    section_suspects,
    thai_digit_document,
)

THAI_LINES = [
    "มาตรา ๙  ภายใต้บังคับกฎหมายว่าด้วยการเหมืองแร่",
    "ให้ไว้ ณ วันที่ ๓๐ พฤศจิกายน พ.ศ. ๒๔๙๗",
    "เป็นปีที่ ๙ ในรัชกาลปัจจุบัน",
    "มาตรา ๑๐  ที่ดินของรัฐซึ่งมิได้มีบุคคลใดมีสิทธิครอบครอง",
    "มาตรา ๑๑  การจัดหาผลประโยชน์ซึ่งที่ดินของรัฐ",
    "๑๒ มาตรา ๙/๑ แก้ไขเพิ่มเติมโดยพระราชบัญญัติ (ฉบับที่ ๑๑) พ.ศ. ๒๕๕๑",
]


class TestThaiDigitDocument:
    def test_detects_thai_numeral_document(self):
        assert thai_digit_document(THAI_LINES) is True

    def test_arabic_document_not_flagged(self):
        assert thai_digit_document(["ปี 2497 มาตรา 9 ข้อ 15 วรรค 3 หน้า 100"]) is False

    def test_too_few_digits_is_not_enough(self):
        """เอกสารที่แทบไม่มีตัวเลข ตัดสินไม่ได้ ต้องไม่เดา"""
        assert thai_digit_document(["ให้ประกาศว่า", "โดยที่เป็นการสมควร"]) is False


class TestRuleLayer:
    def test_superscript_digit_flagged(self):
        """Typhoon อ่านเลขเชิงอรรถไทยยกกำลังออกมาเป็นเลขอารบิกยกกำลัง"""
        found = rule_findings("มาตรา ๘ ทวิ¹⁰ ที่ดินของรัฐ", thai_doc=True)
        assert [(f[2], f[3]) for f in found] == [("๑๐", "เลขยกกำลัง — ควรเป็นเลขไทย")]

    def test_arabic_digit_flagged_in_thai_document(self):
        found = rule_findings("มาตรา 10 ที่ดินของรัฐ", thai_doc=True)
        assert found and found[0][2] == "๑๐"

    def test_arabic_digit_ignored_in_arabic_document(self):
        assert rule_findings("มาตรา 10 ที่ดินของรัฐ", thai_doc=False) == []

    def test_clean_thai_line_is_silent(self):
        assert rule_findings(THAI_LINES[1], thai_doc=True) == []


class TestSectionLengthOutliers:
    """เช็กตัวเองล้วน ๆ ไม่ต้องมี engine อื่นมาเทียบเลย"""

    PAGE = [
        "มาตรา ๑๓  ที่ดินของรัฐ",
        "มาตรา ๑๔๑๓ ให้มีคณะกรรมการ",  # ๑๔ ต่อกับเชิงอรรถ ๑๓ แบบไม่มีช่องว่าง
        "มาตรา ๑๕  กรรมการผู้ทรงคุณวุฒิ",
    ]

    def test_flags_the_line_that_grew_extra_digits(self):
        found = section_length_outliers(self.PAGE)
        assert list(found) == [1]
        start, end, guess, why = found[1][0]
        assert self.PAGE[1][start:end] == "๑๔๑๓"
        assert guess == "๑๔"

    def test_silent_when_every_section_number_is_the_same_length(self):
        page = ["มาตรา ๙ ก", "มาตรา ๑๐ ข", "มาตรา ๑๑ ค"]
        assert section_length_outliers(page) == {}

    def test_too_few_section_numbers_cannot_set_a_baseline(self):
        """มีมาตราแค่ ๒ ค่า คำนวณฐานนิยมไม่น่าเชื่อถือ ต้องไม่เดา"""
        page = ["มาตรา ๙ ก", "มาตรา ๑๐๑๑ ข"]
        assert section_length_outliers(page) == {}

    def test_no_fixed_number_hardcoded_generalises_across_documents(self):
        """เอกสารที่มีมาตราเกิน ๑๑๓ จริงต้องไม่โดนเตือนผิด ถ้าความยาวสม่ำเสมอ"""
        page = [f"มาตรา {n} ก" for n in ("๑๒๐", "๑๒๑", "๑๒๒", "๑๒๓")]
        assert section_length_outliers(page) == {}


class TestSectionFindingsByDocument:
    """หน้าเดียวมักมีเลขมาตราน้อยเกินจะตั้งฐานนิยมได้ ต้องรวมทั้งเอกสารก่อน"""

    def test_baseline_needs_the_whole_document_not_one_page(self):
        pages = {
            "p1": ["มาตรา ๙ ก", "มาตรา ๑๐๑๑ ข"],  # หน้านี้เดียวมีแค่ ๒ ค่า ไม่พอ
            "p2": ["มาตรา ๑๒ ค", "มาตรา ๑๓ ง"],  # รวมกับหน้านี้ครบ ๔ ค่าแล้วตัดสินได้
        }
        found = section_findings_by_document(pages)
        assert list(found) == ["p1"]
        assert found["p1"][1][0][2] == "๑๐"  # ตัดกลับเหลือ ๒ หลักเท่าหน้าอื่น

    def test_unknown_line_index_is_skipped_safely(self):
        assert section_findings_by_document({"p1": ["ไม่มีมาตราเลย"]}) == {}


class TestSectionSuspects:
    """แปลง findings ให้เป็น Suspect — ไม่มีกล่องเพราะไม่ได้ผ่านกริด"""

    def test_builds_a_boxless_suspect_per_flagged_line(self):
        lines = ["มาตรา ๑๓ ก", "มาตรา ๑๔๑๓ ให้มีคณะกรรมการ"]
        findings = {1: [(6, 10, "๑๔", "เลขมาตรายาวผิดปกติ")]}
        out = section_suspects("p1", "typhoon-api-num", lines, findings)
        assert len(out) == 1
        assert out[0].grid_line == 1
        assert out[0].text == lines[1]
        assert out[0].box is None
        assert out[0].findings[0].layer == "rule"

    def test_out_of_range_line_index_is_ignored(self):
        assert section_suspects("p1", "e", ["บรรทัดเดียว"], {5: [(0, 1, "x", "y")]}) == []


class TestVoteLayer:
    def test_majority_disagreement_flagged(self):
        mine = "ตราจองซั่วคราว"
        peers = ["ตราจองชั่วคราว", "ตราจองชั่วคราว"]
        assert cross_engine_findings(mine, peers)

    def test_single_dissenter_ignored(self):
        """engine เดียวที่เห็นต่างไม่พอ — ตัวที่แม่นน้อยจะลากตัวที่แม่นกว่าให้ผิดตาม"""
        mine = "ตราจองชั่วคราว"
        peers = ["ตราจองชั่วคราว", "ตราจองซั่วคราว"]
        assert cross_engine_findings(mine, peers) == []

    def test_all_agree_is_silent(self):
        assert cross_engine_findings("ที่ดินของรัฐ", ["ที่ดินของรัฐ"] * 3) == []

    def test_too_few_peers_is_silent(self):
        assert cross_engine_findings("ที่ดินของรัฐ", ["ที่ดินอื่น"]) == []


class TestFindInLine:
    def test_positions_point_at_the_real_characters(self):
        """ตำแหน่งต้องชี้ตัวอักษรจริงในบรรทัด ไม่ใช่ในสตริงที่จัดรูปแล้ว

        ถ้าแปลงตำแหน่งกลับผิด หน้าเว็บจะไฮไลต์คนละที่กับที่ผิดจริง
        ซึ่งแย่กว่าไม่ไฮไลต์เลย เพราะพาคนตรวจไปดูผิดจุด
        """
        line = "มาตรา ๘ ทวิ¹⁰ ที่ดิน"
        for f in find_in_line(line, [], thai_doc=True):
            assert line[f.start : f.end] == f.text

    def test_spacing_differences_are_not_errors(self):
        """engine ใส่ช่องว่างไม่เหมือนกันเป็นเรื่องปกติ ต้องไม่นับเป็นอ่านผิด"""
        mine = "มาตรา ๙  ภายใต้บังคับ"
        peers = ["มาตรา๙ภายใต้บังคับ", "มาตรา ๙ ภายใต้บังคับ"]
        assert [f for f in find_in_line(mine, peers, thai_doc=True) if f.layer == "vote"] == []


class TestGrid:
    def test_picks_engine_with_fewest_boxed_lines(self):
        """ตัวที่ซอยเกินต้องไม่ได้เป็นแกน — ความผิดพลาดที่เจอจริงคือซอยเกิน"""
        pages = {
            "neat": (["ก", "ข"], [[0, 0, 5, 5], [0, 5, 5, 5]]),
            "shredder": (["ก", "ข", "ค", "ง"], [[0, 0, 2, 2]] * 4),
        }
        assert pick_grid(pages) == "neat"

    def test_engine_without_boxes_cannot_be_grid(self):
        pages = {
            "no_boxes": (["ก"], [None]),
            "boxed": (["ก", "ข"], [[0, 0, 5, 5], [0, 5, 5, 5]]),
        }
        assert pick_grid(pages) == "boxed"

    def test_merged_paragraph_is_split_back_onto_grid(self):
        """VLM รวมสองบรรทัดเป็นก้อนเดียว กริดต้องหั่นกลับให้ตรงบรรทัดในภาพ"""
        pages = {
            "tess": (["ที่ดินของรัฐซึ่งมิได้มีบุคคลใด", "มีสิทธิครอบครองนั้น"],
                     [[0, 0, 100, 10], [0, 10, 100, 10]]),
            "vlm": (["ที่ดินของรัฐซึ่งมิได้มีบุคคลใดมีสิทธิครอบครองนั้น"], [None]),
        }
        rows = build_grid(pages, "tess")
        assert len(rows) == 2
        assert all("vlm" in r.reads for r in rows)


class TestScanPage:
    """ระบุแกนตรง ๆ เพื่อแยกเรื่องการเลือกแกน (มีเทสต์ของตัวเองแล้ว) ออกจากการตรวจ"""

    OK = "พระราชบัญญัติออกตราจองชั่วคราว"

    def _pages(self, vlm_line: str):
        return {
            "tess": ([self.OK], [[10, 20, 300, 40]]),
            "easy": ([self.OK], [[11, 19, 299, 41]]),
            # PaddleOCR ซอยบรรทัดเดียวเป็นชิ้นย่อย — ใส่ไว้ให้เหมือนของจริง
            "paddle": (["พระราชบัญญัติออก", "ตราจองชั่วคราว"],
                       [[12, 21, 150, 38], [160, 21, 138, 38]]),
            "vlm": ([vlm_line], [None]),
        }

    def _scan(self, vlm_line: str):
        return scan_page("p1", "vlm", self._pages(vlm_line),
                         thai_doc=True, grid_engine="tess")

    def test_flags_the_odd_one_out(self):
        sus = self._scan("พระราชบัญญัติออกตราจองซั่วคราว")
        assert len(sus) == 1
        assert "vote" in sus[0].layers

    def test_borrows_a_box_for_an_engine_without_coordinates(self):
        """Typhoon ไม่คืนพิกัด ต้องยืมจากแกนได้ ไม่งั้นครอปภาพไปตรวจไม่ได้"""
        sus = self._scan("พระราชบัญญัติออกตราจองซั่วคราว")
        assert sus[0].box == (10, 20, 300, 40)
        assert sus[0].box_from == "ยืมจาก tess"

    def test_silent_when_every_engine_agrees(self):
        assert self._scan(self.OK) == []

    def test_fragmented_peer_alone_cannot_raise_an_alarm(self):
        """ตัวที่ซอยบรรทัดเกินจะดู "ต่าง" เสมอ ต้องไม่ให้มันเตือนได้ตามลำพัง"""
        pages = {
            "tess": ([self.OK], [[10, 20, 300, 40]]),
            "paddle": (["พระราชบัญญัติออก", "ตราจองชั่วคราว"],
                       [[12, 21, 150, 38], [160, 21, 138, 38]]),
            "vlm": ([self.OK], [None]),
        }
        assert scan_page("p1", "vlm", pages, thai_doc=True, grid_engine="tess") == []

    def test_unknown_engine_returns_nothing(self):
        assert scan_page("p1", "ไม่มีตัวนี้", self._pages("ก"),
                         thai_doc=True, grid_engine="tess") == []
