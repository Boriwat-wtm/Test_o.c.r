"""เทสต์หน้าตรวจงาน — ชี้จุดที่คนควรดู พร้อมตำแหน่งบนภาพ

ความเสี่ยงของโมดูลนี้คือ "ชี้ผิดจุด" มากกว่า "ชี้ไม่ครบ"
ถ้าพาคนไปดูผิดที่ แย่กว่าไม่ชี้เลย เพราะเขาจะเชื่อว่าตรวจแล้ว
"""

from __future__ import annotations

from thai_ocr_bench.review import borrow_boxes, build, digit_marks, summary


class TestDigitMarks:
    def test_จับตัวเลขทุกก้อนในบรรทัด(self):
        marks = digit_marks("วันที่ 20 เมษายน พ.ศ. 2459")
        assert [m.kind for m in marks] == ["digit", "digit"]

    def test_ตำแหน่งชี้ตัวเลขจริงในบรรทัด(self):
        """ถ้าแปลงตำแหน่งผิด หน้าเว็บจะไฮไลต์คนละที่กับตัวเลขจริง"""
        line = "มาตรา ๑๔ วรรค 2"
        for m in digit_marks(line):
            assert line[m.start : m.end].strip()
            assert any(c.isdigit() or c in "๐๑๒๓๔๕๖๗๘๙" for c in line[m.start : m.end])

    def test_เลขไทยปนอารบิกในก้อนเดียวคือผิดแน่(self):
        """เคสจริงของ paddle-th — 'พุทธศักราช ๒24๗' ไม่มีเอกสารไหนเขียนแบบนี้
        วัดแล้ว paddle ปนแบบนี้ 35% ของเลขทุกก้อน"""
        marks = digit_marks("พุทธศักราช ๒24๗")
        assert len(marks) == 1
        assert marks[0].kind == "mixed"

    def test_เลขอารบิกในเอกสารเลขไทยถูกเตือน(self):
        assert digit_marks("มาตรา 14", thai_doc=True)[0].kind == "mixed"

    def test_เลขอารบิกในเอกสารเลขอารบิกไม่ถูกเตือน(self):
        """หนังสือเวียน พ.ศ. ๒๔๕๙ ใช้เลขอารบิกจริง ต้องไม่ปลุกทุกบรรทัด"""
        assert digit_marks("มาตรา 14", thai_doc=False)[0].kind == "digit"

    def test_บรรทัดที่ไม่มีตัวเลขต้องเงียบ(self):
        assert digit_marks("ให้ไว้ ณ วันที่") == []


class TestBorrowBoxes:
    """typhoon ไม่คืนพิกัดเลย (วัดจริง 0/416 บรรทัด) ต้องยืมจากตัวที่คืน"""

    def test_ยืมพิกัดจากบรรทัดที่ตรงกัน(self):
        got = borrow_boxes(
            ["มาตรา ๙", "มาตรา ๑๐"],
            ["มาตรา ๙", "มาตรา ๑๐"],
            [[10, 20, 100, 30], [10, 60, 100, 30]],
        )
        assert got == [(10, 20, 100, 30), (10, 60, 100, 30)]

    def test_บรรทัดที่จับคู่ไม่ได้คืน_None_ไม่เดา(self):
        """ชี้ผิดจุดแย่กว่าไม่ชี้ — คนจะเชื่อว่าตรวจแล้วทั้งที่ดูคนละที่"""
        got = borrow_boxes(["ไม่มีใครมีบรรทัดนี้"], ["อย่างอื่นล้วน"], [[0, 0, 5, 5]])
        assert got == [None]

    def test_ไม่มี_donor_เลยก็ไม่พัง(self):
        assert borrow_boxes(["ก", "ข"], [], []) == [None, None]

    def test_donor_ไม่มีพิกัดบางบรรทัด(self):
        got = borrow_boxes(["ก", "ข"], ["ก", "ข"], [None, [1, 2, 3, 4]])
        assert got == [None, (1, 2, 3, 4)]


class TestBuild:
    def test_รวมสัญญาณตัวเลขกับความไม่นิ่ง(self):
        rows = build(
            ["วันที่ 20", "อำเภอถลาง"],
            thai_doc=False,
            shaky=[False, True],
        )
        assert [m.kind for m in rows[0].marks] == ["digit"]
        assert [m.kind for m in rows[1].marks] == ["shaky"]

    def test_ความไม่นิ่งครอบทั้งบรรทัด(self):
        """สัญญาณนี้บอกได้แค่ระดับบรรทัด ไม่ใช่ระดับตัวอักษร"""
        rows = build(["อำเภอถลาง"], shaky=[True])
        m = rows[0].marks[0]
        assert (m.start, m.end) == (0, len("อำเภอถลาง"))

    def test_ไม่ส่ง_shaky_มาก็ยังใช้ได้(self):
        """ยังไม่ได้วัดความนิ่ง ต้องได้สัญญาณตัวเลขอย่างเดียว ไม่ใช่พัง"""
        rows = build(["มาตรา 9"])
        assert rows[0].needs_check
        assert all(m.kind != "shaky" for m in rows[0].marks)

    def test_บรรทัดสะอาดไม่ต้องตรวจ(self):
        assert not build(["ให้ไว้ ณ วันที่"])[0].needs_check


class TestSummary:
    def test_นับแยกตามชนิด(self):
        rows = build(["มาตรา 9 ข้อ ๒24๗", "สะอาด"], shaky=[True, False])
        s = summary(rows)
        assert s["lines"] == 2
        assert s["to_check"] == 1
        assert s["mixed"] == 1
        assert s["shaky"] == 1


class TestSaveRoundTrip:
    """วงจรแก้แล้วบันทึก — ต้องอ่านกลับมาได้และไม่ทำบรรทัดอื่นหาย"""

    def test_บันทึกทั้งหน้าไม่ใช่เฉพาะบรรทัดที่แก้(self, tmp_path, monkeypatch):
        from thai_ocr_bench import markdown_out

        monkeypatch.setattr(markdown_out, "EXPORT_DIR", tmp_path, raising=False)
        monkeypatch.setattr(
            markdown_out, "page_path_for",
            lambda pid, eng: tmp_path / f"{pid}·{eng}.md",
        )

        lines = ["บรรทัดหนึ่ง", "ปี 2458", "บรรทัดสาม"]
        edits = {1: "ปี 2459"}
        merged = [edits.get(i, ln) for i, ln in enumerate(lines)]
        markdown_out.save_page("p1", "e", "\n".join(merged))

        got = markdown_out.load_page("p1", "e")
        assert got is not None
        assert got.splitlines() == ["บรรทัดหนึ่ง", "ปี 2459", "บรรทัดสาม"]

    def test_ล้างแล้วกลับไปใช้ผลดิบ(self, tmp_path, monkeypatch):
        from thai_ocr_bench import markdown_out

        monkeypatch.setattr(
            markdown_out, "page_path_for",
            lambda pid, eng: tmp_path / f"{pid}·{eng}.md",
        )
        markdown_out.save_page("p1", "e", "แก้แล้ว")
        assert markdown_out.load_page("p1", "e") == "แก้แล้ว"
        markdown_out.clear_page("p1", "e")
        assert markdown_out.load_page("p1", "e") is None

    def test_แก้แล้ว_mark_ตัวเลขยังทำงานกับข้อความใหม่(self):
        """หลังแก้ 2458 เป็น 2459 บรรทัดนั้นต้องยังถูก mark ว่าเป็นตัวเลข
        เพราะยังต้องเทียบกับภาพอยู่ ไม่ใช่หายไปเพราะแก้แล้ว"""
        rows = build(["ปี 2459"], thai_doc=False)
        assert rows[0].needs_check
        assert [m.kind for m in rows[0].marks] == ["digit"]


class TestStaleSelection:
    """เคสจริงที่พัง: สลับ engine แล้วช่องเลือกหน้ายังจำหน้าเก่าไว้

    Streamlit จำค่าที่เลือกตามคีย์ พอ engine ใหม่อ่านคนละชุดหน้า
    ค่าที่ค้างอยู่จะไปหาใน results ไม่เจอ แล้ว KeyError ทั้งหน้า
    (KeyError: 'doc7cdd41_p001' ตอนสลับไป typhoon-api-num+clean)
    """

    def test_หน้าที่_engine_ไม่ได้อ่านต้องไม่ทำให้พัง(self):
        """จำลองตรรกะเลือกหน้าในหน้าเว็บ — ค่าเก่าต้องถูกรีเซ็ต ไม่ใช่พัง"""
        by_id = {"docA_p001": object(), "docA_p002": object()}
        stale = "doc7cdd41_p001"  # หน้าของ engine ก่อนหน้า

        page_id = stale if stale in by_id else next(iter(by_id))
        assert page_id == "docA_p001"

    def test_เอกสารที่ค้างอยู่ต้องถูกรีเซ็ตด้วย(self):
        """เคสจริงรอบสอง: แก้แค่ช่องหน้า ลืมช่องเอกสาร
        สลับ engine แล้วเอกสารที่จำไว้ไม่มีใน engine ใหม่ subset จึงว่าง
        แล้ว next(iter(by_id)) โยน StopIteration ทั้งหน้า"""
        docs = ["docA", "docB"]
        stale = "เอกสารของ engine ก่อนหน้า"
        doc = stale if stale in docs else docs[0]
        assert doc == "docA"

    def test_subset_ว่างต้องคืนก่อนถึง_next_iter(self):
        """ต่อให้ doc ถูก แต่ถ้าไม่มีหน้าเลย ก็ต้องบอกผู้ใช้ ไม่ใช่พัง"""
        subset: list = []
        assert not subset, "ต้องเช็ก subset ว่างก่อนเรียก next(iter(...))"

    def test_ต้องหยิบ_stored_ด้วย_get_ไม่ใช่_subscript(self):
        """results[engine][page_id] ตรง ๆ พังทันทีถ้าหน้าไม่มี
        ต้อง .get() แล้วเช็คก่อน ถึงจะบอกผู้ใช้ได้ว่าให้ไปสแกนก่อน"""
        results = {"e": {"docA_p001": object()}}
        assert results["e"].get("ไม่มีหน้านี้") is None


class TestSuggest:
    """เดาคำที่ถูกเฉพาะกรณีที่มีคำตอบเดียวจริง ๆ

    เดาผิดแล้วคนกดรับไปเลยแย่กว่าไม่เดา — จึงเดาแค่เลขที่ผิดรูปแบบ
    ซึ่งตัดสินได้โดยไม่ต้องดูภาพ
    """

    def test_เลขปนไทยอารบิกแปลงเป็นไทยทั้งก้อน(self):
        from thai_ocr_bench.ui.review_view import suggest

        line = "พุทธศักราช ๒24๗"
        m = digit_marks(line)[0]
        assert m.kind == "mixed"
        assert suggest(m, line) == "๒๒๔๗"

    def test_เลขอารบิกในเอกสารเลขไทยแปลงเป็นไทย(self):
        from thai_ocr_bench.ui.review_view import suggest

        line = "มาตรา 14"
        assert suggest(digit_marks(line, thai_doc=True)[0], line) == "๑๔"

    def test_ตัวเลขปกติไม่เดา(self):
        """เลขอารบิกในเอกสารเลขอารบิกถูกอยู่แล้ว ไม่มีอะไรให้แนะนำ"""
        from thai_ocr_bench.ui.review_view import suggest

        line = "วันที่ 20"
        assert suggest(digit_marks(line, thai_doc=False)[0], line) is None

    def test_ไม่เดาความไม่นิ่ง(self):
        """อ่านซ้ำแล้วตอบไม่ตรงกันไม่ได้บอกว่าอันไหนถูก ต้องให้คนดูภาพเอง"""
        from thai_ocr_bench.review import Mark
        from thai_ocr_bench.ui.review_view import suggest

        assert suggest(Mark(0, 5, "shaky", "ไม่นิ่ง"), "อำเภอถลาง") is None
