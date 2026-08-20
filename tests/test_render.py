"""เทสต์การเลือก zoom ตอน render — ความเสี่ยงคือ "ลดผิดหน้า"

การ cap ผิดไม่ทำให้อะไรพัง มันแค่ส่งภาพ 72 DPI ให้ OCR แล้วคะแนนตกเฉย ๆ
โดยไม่มี error ให้เห็น เทสต์จึงคุมสองด้าน: ต้องลดเมื่อหน้าเป็นสแกนหยาบจริง
และต้องไม่แตะหน้าที่มีรายละเอียดให้ขยาย
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from thai_ocr_bench.render import _capped_zoom

ZOOM = 300 / 72.0


def make_page(
    width: float, height: float, images: list[tuple[int, pymupdf.Rect]], *, text: str = ""
) -> pymupdf.Page:
    """หน้าเปล่าที่วางภาพขนาด px ตามที่สั่งลงในกรอบที่กำหนด"""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    for px, rect in images:
        buf = io.BytesIO()
        Image.new("RGB", (px, px), "gray").save(buf, format="PNG")
        page.insert_image(rect, stream=buf.getvalue())
    if text:
        page.insert_text((72, height / 2), text)
    return page


def test_สแกนที่เอา_px_มาใส่เป็น_pt_ถูกลดลงเหลือ_1() -> None:
    """เคสที่เป็นเหตุให้มีฟังก์ชันนี้: หน้า 2480pt คู่กับภาพ 2480px = 72 DPI"""
    page = make_page(2480, 2480, [(2480, pymupdf.Rect(0, 0, 2480, 2480))])
    assert _capped_zoom(page, ZOOM) == pytest.approx(1.0)


def test_โลโก้เล็กความละเอียดต่ำไม่ลากทั้งหน้าลง() -> None:
    """หน้า A4 ปกติที่มีโลโก้รูปเดียว เคยถูก cap เหลือ 72 DPI ทั้งหน้า"""
    page = make_page(595, 842, [(120, pymupdf.Rect(40, 40, 120, 120))], text="ทดสอบ")
    assert _capped_zoom(page, ZOOM) == pytest.approx(ZOOM)


def test_ภาพละเอียดที่แปะทับพื้นหลังหยาบเป็นตัวตัดสิน() -> None:
    """พื้นหลัง 72 DPI แต่มีเอกสาร 300 DPI แปะอยู่ ต้อง render ตามตัวที่ละเอียดกว่า"""
    page = make_page(
        595,
        842,
        [
            (595, pymupdf.Rect(0, 0, 595, 842)),  # เต็มหน้าแต่หยาบ
            (1250, pymupdf.Rect(100, 100, 400, 400)),  # 300 DPI
        ],
    )
    assert _capped_zoom(page, ZOOM) == pytest.approx(ZOOM)


def test_หน้าหมุน_90_องศาคิด_dpi_ถูก() -> None:
    """page.rect เป็นค่าหลังหมุน ถ้าเอาไปหารกับ px ดิบจะเพี้ยนตามด้านที่สลับกัน"""
    page = make_page(842, 595, [(3507, pymupdf.Rect(0, 0, 842, 595))])
    page.set_rotation(90)
    assert page.rect.width == pytest.approx(595, abs=1)  # ยืนยันว่าหมุนจริง
    assert _capped_zoom(page, ZOOM) == pytest.approx(ZOOM)


def test_หน้า_vector_ล้วนไม่ถูกแตะ() -> None:
    """ไม่มีภาพเลย ยิ่ง render ละเอียดยิ่งได้ตัวหนังสือคม"""
    page = make_page(595, 842, [], text="ข้อความ vector")
    assert _capped_zoom(page, ZOOM) == pytest.approx(ZOOM)


def test_ภาพหยาบบนหน้าที่มี_text_layer_ไม่ถูก_cap() -> None:
    """text layer ไม่ได้ถูกจำกัดด้วยความละเอียดของภาพที่อยู่ข้าง ๆ"""
    page = make_page(
        595, 842, [(595, pymupdf.Rect(0, 0, 595, 842))], text="มีข้อความจริง"
    )
    assert _capped_zoom(page, ZOOM) == pytest.approx(ZOOM)
