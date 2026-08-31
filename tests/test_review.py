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
