"""เทสต์ของตัวจัดข้อความ — ถ้าตัวนี้ผิด ตัวเลขทั้ง benchmark ผิดหมด"""

from __future__ import annotations

from thai_ocr_bench.metrics import compare
from thai_ocr_bench.thai_text import (
    classify_char,
    compose_sara_am,
    drop_duplicate_marks,
    normalize,
    reorder_marks,
    thai_to_arabic_digits,
)
from thai_ocr_bench.truth import (
    join_split_sara_am,
    needs_sara_repair,
    repair_sara,
)


class TestReorderMarks:
    def test_tone_moves_after_vowel(self):
        # ไม้เอก + สระอิ  ต้องกลายเป็น สระอิ + ไม้เอก
        assert reorder_marks("ก่ิ") == "กิ่"

    def test_already_ordered_unchanged(self):
        assert reorder_marks("กิ่") == "กิ่"

    def test_below_vowel_before_tone(self):
        assert reorder_marks("กุ้") == "กุ้"

    def test_plain_text_untouched(self):
        assert reorder_marks("ประกาศ") == "ประกาศ"


class TestSaraAm:
    def test_nikhahit_plus_aa_becomes_am(self):
        assert compose_sara_am("กํา") == "กำ"

    def test_normalize_treats_both_forms_as_equal(self):
        assert normalize("กำ") == normalize("กํา")


class TestDuplicateMarks:
    def test_repeated_tone_collapsed(self):
        assert drop_duplicate_marks("ก่่") == "ก่"

    def test_different_marks_kept(self):
        assert drop_duplicate_marks("กิ่") == "กิ่"


class TestNormalize:
    def test_spaces_stripped_by_default(self):
        # Tesseract แทรกช่องว่างระหว่างตัวอักษร ต้องตัดทิ้งก่อนเทียบ
        assert normalize("ม ิ ต ิ ด ้ า น") == normalize("มิติด้าน")

    def test_keep_spaces_collapses_only(self):
        assert normalize("ก  ข   ค", keep_spaces=True) == "ก ข ค"


class TestThaiDigits:
    def test_conversion(self):
        assert thai_to_arabic_digits("๒๕๖๙") == "2569"

    def test_zero_included(self):
        assert thai_to_arabic_digits("๐") == "0"


class TestClassify:
    def test_classes(self):
        assert classify_char("ก") == "thai_consonant"
        assert classify_char("่") == "thai_vowel_mark"
        assert classify_char("า") == "thai_vowel_mark"
        assert classify_char("๕") == "thai_digit"
        assert classify_char("5") == "arabic_digit"
        assert classify_char("A") == "latin"
        assert classify_char("ฯ") == "punct_symbol"


class TestSaraRepair:
    def test_detects_broken_mapping(self):
        assert needs_sara_repair("ส ำนักงำน")
        assert not needs_sara_repair("สำนักงาน")

    def test_repairs_real_sample(self):
        broken = "ส ำนักงำนคณะกรรมกำรกฤษฎีกำ"
        assert repair_sara(broken) == "สำนักงานคณะกรรมการกฤษฎีกา"

    def test_repairs_law_heading(self):
        assert repair_sara("พระรำชบัญญัติ") == "พระราชบัญญัติ"


class TestCompare:
    def test_perfect_match(self):
        score = compare("ประกาศ ณ วันที่ ๒", "ประกาศ ณ วันที่ ๒")
        assert score.cer == 0.0
        assert all(s.kind == "ok" for s in score.spans)

    def test_wrong_thai_digit_is_caught(self):
        score = compare("วันที่ ๒", "วันที่ ๗")
        assert score.cer > 0
        assert score.total_by_class["thai_digit"] == 1
        assert score.correct_by_class["thai_digit"] == 0
        assert any(s.kind == "wrong" for s in score.spans)

    def test_missing_text_marked(self):
        score = compare("ประกาศ", "ประ")
        assert any(s.kind == "missing" for s in score.spans)

    def test_spacing_noise_does_not_count_as_error(self):
        # ปัญหาจริงของ Tesseract: แทรกช่องว่างเต็มไปหมด แต่ตัวอักษรถูก
        score = compare("มิติด้าน", "ม ิ ต ิ ด ้ า น")
        assert score.cer == 0.0

    def test_lenient_digits_accepts_arabic(self):
        strict = compare("๒๕๖๗", "2567")
        lenient = compare("๒๕๖๗", "2567", lenient_digits=True)
        assert strict.cer > 0
        assert lenient.cer == 0.0


class TestJoinSplitSaraAm:
    """สระอำที่ถูกหั่นเป็น 'พยัญชนะ + ช่องว่าง + สระอา' ตอนดึง text layer

    คนละอาการกับที่ repair_sara ซ่อม และถ้าไม่ซ่อมจะกลายเป็นลงโทษ engine
    ที่อ่านถูก เพราะตัววัดตัดช่องว่างทิ้งก่อนเทียบ 'ท า' จึงกลายเป็น 'ทา'
    แล้วชนกับ 'ทำ' (วัดจริง: 113 จุดในกฎกระทรวง ๕๙ ดัน CER ขึ้น ~1.2 จุด)
    """

    def test_ต่อคำที่ถูกหั่นกลับได้(self):
        assert join_split_sara_am("อาศัยอ านาจตามความ") == "อาศัยอำนาจตามความ"
        assert join_split_sara_am("การท าประโยชน์") == "การทำประโยชน์"
        assert join_split_sara_am("ส านักงานที่ดิน") == "สำนักงานที่ดิน"

    def test_ไม่แตะข้อความที่ถูกอยู่แล้ว(self):
        ok = "สำนักงานคณะกรรมการกฤษฎีกา"
        assert join_split_sara_am(ok) == ok

    def test_ไม่กินช่องว่างระหว่างคำปกติ(self):
        """ช่องว่างที่ตามด้วยตัวอื่นซึ่งไม่ใช่สระอา ต้องอยู่ครบ"""
        line = "มาตรา ๙ ภายใต้บังคับกฎหมาย"
        assert join_split_sara_am(line) == line

    def test_ช่องว่างหน้าสระอาที่ไม่มีพยัญชนะนำต้องไม่ถูกแตะ(self):
        """กฎผูกกับพยัญชนะนำหน้าเสมอ ไม่ใช่จับ ' า' ลอย ๆ"""
        assert join_split_sara_am("๙ าก") == "๙ าก"
