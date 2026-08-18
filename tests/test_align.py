"""เทสต์การจับคู่บรรทัด — จุดที่ตัวเลข "อ่านครบ" กับ "CER บรรทัด" เกิดขึ้น

เทสต์ชุดนี้มีเพราะเคยพลาดมาแล้วจริง ๆ: Typhoon อ่านหน้าหนึ่งถูกเกือบทุกตัว
(CER ทั้งหน้า ๐.๐๔%) แต่หน้าเว็บรายงานว่า "อ่านได้ ๙ จาก ๓๔ บรรทัด"
เพราะมันคืนย่อหน้าเป็นก้อนเดียว ไม่แบ่งตามบรรทัดในภาพ
ตัวเลขที่ผิดแบบนี้อันตรายกว่าไม่มีตัวเลข เพราะทำให้ตัดสินใจเลือก engine ผิด
"""

from __future__ import annotations

from thai_ocr_bench.engines.typhoon_api import _strip_markdown
from thai_ocr_bench.metrics import align_lines, split_by_truth
from thai_ocr_bench.thai_text import fold_typography, normalize

# ย่อหน้าเดียวที่ในภาพถูกตัดเป็นสามบรรทัด
WRAPPED = [
    "มาตรา ๙  ภายใต้บังคับกฎหมายว่าด้วยการเหมืองแร่และการป่าไม้ ที่ดินของรัฐนั้น",
    "ถ้ามิได้มีสิทธิครอบครอง หรือมิได้รับอนุญาตจากพนักงานเจ้าหน้าที่แล้ว",
    "ห้ามมิให้บุคคลใดเข้าไปยึดถือ ครอบครอง รวมตลอดถึงการก่นสร้างหรือเผาป่า",
]
MERGED = " ".join(WRAPPED)


class TestMergedParagraph:
    def test_all_lines_found(self):
        """OCR รวมสามบรรทัดเป็นก้อนเดียว ต้องยังนับว่าอ่านครบทั้งสามบรรทัด"""
        score = align_lines(WRAPPED, [MERGED])
        assert score.missed_lines == 0
        assert score.recall == 1.0

    def test_no_false_errors(self):
        """อ่านถูกทุกตัว ต่อให้แบ่งบรรทัดไม่เหมือนกัน CER ต้องเป็นศูนย์"""
        score = align_lines(WRAPPED, [MERGED])
        assert score.matched_cer == 0.0

    def test_split_back_into_lines(self):
        """ต้องหั่นก้อนกลับเป็นทีละบรรทัด เพื่อให้หน้าเว็บเทียบกับรูปได้"""
        score = align_lines(WRAPPED, [MERGED])
        pairs = [p for p in score.pairs if p.truth_index is not None]
        assert len(pairs) == len(WRAPPED)
        for pair in pairs:
            assert normalize(pair.pred) == normalize(pair.truth)

    def test_not_counted_as_spurious(self):
        score = align_lines(WRAPPED, [MERGED])
        assert score.spurious_lines == 0


class TestDoesNotOverReach:
    """ด่านกันคะแนนสวยเกินจริง — สำคัญพอ ๆ กับการนับให้ครบ"""

    def test_unread_line_stays_missed(self):
        """บรรทัดที่ OCR ไม่ได้อ่าน ต้องไม่ถูกกลืนเข้ากลุ่มของย่อหน้าอื่น"""
        truth = [*WRAPPED, "บทเฉพาะกาลนี้ไม่มีในผลของ OCR เลยแม้แต่คำเดียว"]
        score = align_lines(truth, [MERGED])
        assert score.missed_lines == 1

    def test_short_line_not_glued_to_unrelated_block(self):
        """คำสั้นที่บังเอิญโผล่ในย่อหน้าอื่น ต้องไม่ถูกนับว่าอ่านเจอ

        "กฎกระทรวง" โผล่อยู่กลางย่อหน้าที่ไม่เกี่ยวกัน
        partial_ratio จะให้ ๑๐๐ เต็ม ด่านตรวจทั้งกลุ่มต้องปัดตกให้ได้
        """
        truth = ["กฎกระทรวง"]
        pred = ["หลักเกณฑ์และวิธีการจัดหาผลประโยชน์ ให้กำหนดโดยกฎกระทรวง "
                "แต่สำหรับการขาย การแลกเปลี่ยน และการให้เช่าซื้อที่ดิน"]
        assert align_lines(truth, pred).missed_lines == 1

    def test_line_engine_unaffected(self):
        """engine ที่แบ่งบรรทัดตามภาพอยู่แล้ว ผลต้องไม่เปลี่ยน"""
        score = align_lines(WRAPPED, WRAPPED)
        assert score.recall == 1.0
        assert score.matched_cer == 0.0
        assert score.spurious_lines == 0


class TestSplitByTruth:
    def test_pieces_match_truth(self):
        pieces = split_by_truth(WRAPPED, MERGED)
        assert len(pieces) == len(WRAPPED)
        assert [normalize(p) for p in pieces] == [normalize(t) for t in WRAPPED]

    def test_single_line_passthrough(self):
        assert split_by_truth(["กฎกระทรวง"], "กฎกระทรวง") == ["กฎกระทรวง"]


class TestFoldTypography:
    def test_curly_quotes_match_straight(self):
        """ต้นฉบับใช้อัญประกาศโค้ง VLM คืนอัญประกาศตรง — ต้องไม่นับเป็นอ่านผิด"""
        assert normalize("“ที่ดิน”") == normalize('"ที่ดิน"')

    def test_superscript_digit_becomes_arabic(self):
        """เลขไทยยกกำลังที่ถูกอ่านเป็น ¹⁰ ต้องยังตกเกณฑ์ strict แต่ผ่าน lenient"""
        assert fold_typography("¹⁰") == "10"
        assert normalize("มาตรา๑๐") != normalize("มาตรา¹⁰")

    def test_dashes_folded(self):
        assert fold_typography("–—−") == "---"

    def test_thai_text_untouched(self):
        thai = "ที่ดินของรัฐ ๒๕๖๙"
        assert fold_typography(thai) == thai


class TestStripMarkdown:
    def test_page_number_tag_removed_content_kept(self):
        """เลขหน้าอยู่ในเฉลย ต้องเก็บข้อความไว้แต่ถอดแท็กออก"""
        assert _strip_markdown("<page_number>- ๘ -</page_number>") == "- ๘ -"

    def test_figure_tag_removed(self):
        assert _strip_markdown("<figure>ตราครุฑ</figure>") == "ตราครุฑ"

    def test_plain_line_unchanged(self):
        assert _strip_markdown("มาตรา ๙  ที่ดินของรัฐ") == "มาตรา ๙  ที่ดินของรัฐ"

    def test_table_rule_dropped(self):
        assert _strip_markdown("|---|---|") == ""
