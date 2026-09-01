"""รันหน้าเว็บทั้งหน้าจริง ๆ แล้วดูว่ามี exception ไหม

ทำไมต้องมี — ตอนแยก app.py 1,731 บรรทัดออกเป็น ui/ ไฟล์ละแท็บ มี import
ตกหล่นไปหนึ่งตัว (dataclasses.replace) ซึ่งพังทุกครั้งที่เปิดหน้าเว็บ
แต่วิธีตรวจที่ใช้ตอนนั้นจับไม่ได้เลย
  - import ทีละโมดูลผ่าน       เพราะ replace ถูกเรียกตอนรัน ไม่ใช่ตอน import
  - เทสต์เดิม 103 ตัวผ่านหมด   เพราะไม่มีตัวไหนแตะโค้ดหน้าเว็บ
  - เปิด URL ได้ HTTP 200      เพราะ Streamlit ตอบ 200 แล้วค่อยโชว์ error ในหน้า

AppTest รันสคริปต์จริงแบบเดียวกับที่เบราว์เซอร์ทำ จึงเป็นตัวเดียวที่จับได้
และเพราะ st.tabs() รันเนื้อหาทุกแท็บทุกรอบ (แค่ซ่อนด้วย CSS ไม่ใช่ lazy)
การรันครั้งเดียวจึงครอบคลุมทั้ง 8 แท็บ

เทสต์นี้พึ่งข้อมูลจริงใน data/ กับ results/ ซึ่งไม่ได้อยู่ใน git
เครื่องที่ยังไม่ได้ render ภาพจะถูกข้าม ไม่ใช่ฟ้องว่าพัง
"""

from __future__ import annotations

import pytest

from thai_ocr_bench.config import IMAGE_DIR

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

# ตัวนี้รันสคริปต์หน้าเว็บทั้งหน้าจริง จึงใช้เวลาราว 2 นาที ซึ่งกลบเทสต์
# ที่เหลือทั้งชุด (111 ตัวรวมกันไม่ถึง 1 วินาที) ติด marker slow ไว้ให้
# `pytest` เฉย ๆ ข้ามไป แล้วรันเองตอนแตะโค้ดหน้าเว็บด้วย `pytest -m slow`
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not IMAGE_DIR.exists() or not any(IMAGE_DIR.glob("*.png")),
        reason="ยังไม่มีภาพใน data/images — รัน render_pages.py ก่อน",
    ),
]


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=300)
    at.run()
    return at


def test_ไม่มี_exception_ตอนเปิดหน้าเว็บ(app: AppTest) -> None:
    """ข้อความ error ต้องบอกให้ชัดว่าพังตรงไหน ไม่ใช่แค่ assert เปล่า ๆ"""
    assert not app.exception, "\n".join(str(e) for e in app.exception)


def test_แท็บครบทุกอัน(app: AppTest) -> None:
    """เช็กว่าแท็บระดับบนครบตาม TABS

    app.tabs นับแท็บทุกระดับรวมแท็บซ้อนในเนื้อหาด้วย (แท็บตรวจงานมี
    "ตรวจทีละจุด/ดูทั้งหน้า" ซ้อนอยู่ข้างใน) เทียบจำนวนตรง ๆ จึงพังทุกครั้ง
    ที่มีใครเพิ่มแท็บซ้อน ทั้งที่ไม่ใช่ความผิดพลาด — เช็กจากชื่อแทน
    """
    from app import TABS

    labels = {t.label for t in app.tabs}
    missing = [name for name, _ in TABS if name not in labels]
    assert not missing, f"แท็บระดับบนหายไป: {missing}"


def test_แต่ละแท็บวาดอะไรออกมาจริง(app: AppTest) -> None:
    """กันกรณีที่ไม่ error แต่ทุกแท็บว่างเปล่า ซึ่งก็คือพังเหมือนกัน

    ไม่เช็กว่าแท็บไหนวาดอะไร เพราะผูกกับข้อมูลในเครื่องมากเกินไป
    เอาแค่ว่ามีทั้งตารางและตัวเลขโผล่ออกมา แปลว่า view ทำงานถึงปลายทาง
    """
    assert app.dataframe, "ไม่มีตารางเลยสักอัน"
    assert app.metric, "ไม่มีเมตริกเลยสักอัน"


def test_กดเลขบรรทัดแล้วได้ช่องแก้ตรงบรรทัดนั้น() -> None:
    """หัวใจของหน้าตรวจงาน — กดเลขบรรทัดแล้วต้องแก้ได้ตรงที่เดิม

    ทำไมต้องมีเทสต์นี้: การแก้ทีละบรรทัดพึ่ง session_state สามคีย์ที่ต้อง
    สอดคล้องกัน (rv_ln ที่ผูกกับหน้า+engine, คีย์ปุ่ม, คีย์ช่องพิมพ์) ถ้าคีย์
    ไหนหลุด ปุ่มจะกดแล้วไม่มีอะไรเกิดขึ้น ซึ่งไม่โยน exception ให้จับ
    """
    at = AppTest.from_file("app.py", default_timeout=300)
    at.run()
    assert not at.exception, "\n".join(str(e) for e in at.exception)

    nums = [b for b in at.button if b.key and b.key.startswith("rvln|")]
    if not nums:
        pytest.skip("หน้าที่เลือกไว้ไม่มีบรรทัดให้ตรวจ")

    nums[0].click().run()
    assert not at.exception, "\n".join(str(e) for e in at.exception)

    line = nums[0].key.split("|")[-1]
    boxes = [t for t in at.text_input if t.key and t.key.endswith(f"|{line}")]
    assert boxes, f"กดบรรทัด {line} แล้วไม่มีช่องพิมพ์โผล่มา"

    # ยกเลิกแล้วต้องกลับเป็นโหมดอ่าน ไม่ค้างเป็นช่องพิมพ์
    cancel = [b for b in at.button if b.key and b.key.startswith("rvno|")]
    assert cancel, "ไม่มีปุ่มยกเลิกให้กดกลับ"
    cancel[0].click().run()
    assert not at.exception, "\n".join(str(e) for e in at.exception)
    assert not [t for t in at.text_input if t.key and t.key.startswith("rvtxt|")]
