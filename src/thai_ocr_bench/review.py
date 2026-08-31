"""เตรียมข้อมูลสำหรับ "หน้าตรวจงาน" — ชี้จุดที่คนควรดู พร้อมตำแหน่งบนภาพ

รวมสองสัญญาณที่วัดแล้วว่าคุ้มที่สุด เข้าด้วยกันในมุมมองเดียว

  ตัวเลข        กินพื้นที่ 2.8% ของหน้า แต่ครอบคลุมความผิด 45% ของทั้งหมด
                ไม่มีวิธีไหนให้อัตราส่วนดีเท่านี้ และตัวเลขตรวจเร็วมาก
                กวาดตาเทียบกับภาพได้ทันที ต่างจากการอ่านทั้งบรรทัด

  ความไม่นิ่ง    จับของที่โมเดลแต่งขึ้นมาเอง ซึ่งตัวเลขจับไม่ได้
                (เช่น "อำเภอถลาง" ที่ควรเป็น "อำมาตย์โท." — ไม่มีตัวเลขเลย)

ทำไมต้องยืมพิกัดจาก engine อื่น — ตระกูล typhoon ไม่คืนตำแหน่งข้อความเลย
วัดจริง 0 จาก 416 บรรทัด ส่วน tesseract คืนครบ 752/752 ถ้าไม่ยืม คนตรวจ
ต้องกวาดตาหาเองทั้งหน้าว่าบรรทัดที่ระบบ mark อยู่ตรงไหนของภาพ ซึ่งทำให้
การ mark แทบไม่มีประโยชน์

ทำไมไม่ให้ engine ที่ยืมพิกัดมาแก้ข้อความด้วย — วัดแล้วบนหน้าเดียวกัน 24 หน้า
  typhoon อ่านเลขถูกคนเดียว    134 ตัว
  tesseract อ่านเลขถูกคนเดียว     1 ตัว
เอามาโหวตกันจะทำให้แย่ลง เพราะตัวที่แม่นน้อยกว่าจะลากตัวที่แม่นกว่าผิดตาม
มันมีหน้าที่เดียวคือบอกว่าบรรทัดนี้อยู่ตรงไหน
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# เลขไทยกับเลขอารบิกติดกันเป็นก้อนเดียว — "๒24๗" ต้องถูกมองเป็นก้อนเดียว
# ไม่ใช่สามก้อน เพราะการปนกันเองคือสัญญาณว่าอ่านผิด
_DIGITS = re.compile(r"[0-9๐-๙]+")
_THAI_DIGITS = set("๐๑๒๓๔๕๖๗๘๙")


@dataclass
class Mark:
    """ช่วงหนึ่งในบรรทัดที่ควรให้คนดู"""

    start: int
    end: int
    kind: str  # "digit" | "mixed" | "shaky"
    note: str


@dataclass
class ReviewLine:
    index: int
    text: str
    marks: list[Mark] = field(default_factory=list)
    box: tuple[int, int, int, int] | None = None

    @property
    def needs_check(self) -> bool:
        return bool(self.marks)


def digit_marks(line: str, *, thai_doc: bool | None = None) -> list[Mark]:
    """หาช่วงตัวเลขทุกก้อนในบรรทัด และแยกก้อนที่ปนไทย-อารบิกออกมา

    ก้อนที่ปนกันเองตัดสินได้เลยว่าผิด ไม่ต้องเปิดภาพดู — ไม่มีเอกสารไหน
    เขียน "พุทธศักราช ๒24๗" วัดจริง paddle-th ปนแบบนี้ 35% ของเลขทุกก้อน
    ส่วน tesseract 2% และ easyocr 7%

    thai_doc ใช้ตัดสินว่าเลขอารบิกล้วนในเอกสารเลขไทยควรเตือนไหม
    ส่งเป็น None ถ้าไม่รู้ (จะไม่เตือนเรื่องนี้)
    """
    out: list[Mark] = []
    for m in _DIGITS.finditer(line):
        token = m.group()
        has_thai = any(c in _THAI_DIGITS for c in token)
        has_arabic = any(c.isdigit() and c not in _THAI_DIGITS for c in token)

        if has_thai and has_arabic:
            out.append(
                Mark(m.start(), m.end(), "mixed", "เลขไทยปนอารบิกในก้อนเดียว — ผิดแน่")
            )
        elif thai_doc and not has_thai:
            out.append(
                Mark(m.start(), m.end(), "mixed", "เอกสารนี้ใช้เลขไทย แต่ก้อนนี้เป็นอารบิก")
            )
        else:
            out.append(Mark(m.start(), m.end(), "digit", "ตัวเลข — เทียบกับภาพ"))
    return out


def borrow_boxes(
    lines: list[str],
    donor_lines: list[str],
    donor_boxes: list[list[int] | None],
) -> list[tuple[int, int, int, int] | None]:
    """จับคู่บรรทัดของเรากับของ engine ที่คืนพิกัด แล้วยืมพิกัดมา

    ใช้ align_lines ตัวเดียวกับที่ใช้วัดคะแนน ไม่เขียนวิธีจับคู่ขึ้นใหม่
    เพราะมันรองรับกรณีที่ VLM รวมหลายบรรทัดเป็นย่อหน้าเดียวอยู่แล้ว

    บรรทัดที่จับคู่ไม่ได้คืน None ดีกว่าเดาพิกัดมั่ว — ชี้ผิดจุดแย่กว่าไม่ชี้
    """
    from .metrics import align_lines

    out: list[tuple[int, int, int, int] | None] = [None] * len(lines)
    if not donor_lines:
        return out

    # ใช้ฝั่งเราเป็น "เฉลย" เพื่อให้ align_lines หั่นบรรทัดของ donor มาเทียบทีละบรรทัด
    for pair in align_lines(lines, donor_lines).pairs:
        i = getattr(pair, "truth_index", None)
        j = getattr(pair, "pred_index", None)
        if i is None or j is None or not (0 <= i < len(out)):
            continue
        if 0 <= j < len(donor_boxes) and donor_boxes[j]:
            out[i] = tuple(donor_boxes[j])  # type: ignore[assignment]
    return out


def build(
    lines: list[str],
    *,
    thai_doc: bool | None = None,
    shaky: list[bool] | None = None,
    donor_lines: list[str] | None = None,
    donor_boxes: list[list[int] | None] | None = None,
) -> list[ReviewLine]:
    """รวมทุกสัญญาณเป็นรายการบรรทัดพร้อมตรวจ

    shaky มาจาก measure_stability.py — บรรทัดที่อ่านซ้ำแล้วตอบไม่ตรงกัน
    ส่งเป็น None ถ้ายังไม่ได้วัด (จะมีแต่สัญญาณตัวเลข)
    """
    boxes = (
        borrow_boxes(lines, donor_lines, donor_boxes)
        if donor_lines is not None and donor_boxes is not None
        else [None] * len(lines)
    )

    out: list[ReviewLine] = []
    for i, text in enumerate(lines):
        marks = digit_marks(text, thai_doc=thai_doc)
        if shaky and i < len(shaky) and shaky[i]:
            # ครอบทั้งบรรทัด เพราะความไม่นิ่งบอกได้แค่ระดับบรรทัด ไม่ใช่ระดับตัวอักษร
            marks.append(Mark(0, len(text), "shaky", "อ่านซ้ำแล้วตอบไม่ตรงกัน"))
        out.append(ReviewLine(index=i, text=text, marks=marks, box=boxes[i]))
    return out


def summary(rows: list[ReviewLine]) -> dict[str, int]:
    """ตัวเลขสรุปสำหรับหัวหน้าเว็บ"""
    kinds = [m.kind for r in rows for m in r.marks]
    return {
        "lines": len(rows),
        "to_check": sum(1 for r in rows if r.needs_check),
        "digits": kinds.count("digit"),
        "mixed": kinds.count("mixed"),
        "shaky": kinds.count("shaky"),
        "with_box": sum(1 for r in rows if r.box),
    }
