"""เทสต์ตัวตรวจลายน้ำ — ความเสี่ยงคือ "ลบผิดหน้า"

ลบลายน้ำที่ไม่มีอยู่จริง = เอาจุดตัดไปกินขอบสระกับวรรณยุกต์ของภาพสแกน
ซึ่งเป็นสิ่งที่เรากำลังวัดพอดี เทสต์จึงคุมทั้งสองด้าน
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from thai_ocr_bench.preprocess import has_watermark, remove_watermark, separation

SIZE = (400, 400)


def page_with_watermark() -> Image.Image:
    """ตัวหนังสือดำ + ลายน้ำเทาเฉดเดียว มีหลุมว่างคั่นสองกลุ่ม"""
    a = np.full(SIZE, 252, dtype=np.uint8)
    a[10:60, :] = 20  # ตัวหนังสือ
    a[100:180, :] = 238  # ลายน้ำ เฉดเดียวล้วน
    return Image.fromarray(a, mode="L")


def scanned_page() -> Image.Image:
    """สแกนพื้นเทา ไล่เฉดต่อเนื่องจากดำไปขาว ไม่มีหลุม"""
    a = np.full(SIZE, 250, dtype=np.uint8)
    ramp = np.linspace(20, 244, 180).astype(np.uint8)
    a[20:200, :] = ramp[:, None]
    return Image.fromarray(a, mode="L")


def test_จับลายน้ำจริงได้() -> None:
    assert has_watermark(page_with_watermark())


def test_ไม่หลงว่าสแกนพื้นเทาคือลายน้ำ() -> None:
    """เคสที่เป็นเหตุให้ต้องเพิ่ม separation — เดิมหน้านี้ถูกลบทิ้ง"""
    assert not has_watermark(scanned_page())


def test_หน้าสะอาดไม่ถูกแตะ() -> None:
    assert not has_watermark(Image.fromarray(np.full(SIZE, 255, dtype=np.uint8), "L"))


def test_separation_แยกสองแบบออกจากกันชัด() -> None:
    """ต้องห่างกันพอให้จุดตัด 4.0 ไม่ใช่การฟลุก"""
    assert separation(page_with_watermark()) > 4.0
    assert separation(scanned_page()) < 4.0


def test_ลบแล้วตัวหนังสือยังอยู่ครบ() -> None:
    """คงค่าเดิมของพิกเซลที่เข้มกว่าจุดตัด ไม่ทำเป็นขาวดำสองระดับ"""
    before = np.asarray(page_with_watermark())
    after = np.asarray(remove_watermark(page_with_watermark()))
    ink = before < 215
    assert np.array_equal(after[ink], before[ink])
    assert (after[100:180, :] == 255).all()  # ลายน้ำหายหมด
