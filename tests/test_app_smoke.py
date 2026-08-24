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

pytestmark = pytest.mark.skipif(
    not IMAGE_DIR.exists() or not any(IMAGE_DIR.glob("*.png")),
    reason="ยังไม่มีภาพใน data/images — รัน render_pages.py ก่อน",
)


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=300)
    at.run()
    return at


def test_ไม่มี_exception_ตอนเปิดหน้าเว็บ(app: AppTest) -> None:
    """ข้อความ error ต้องบอกให้ชัดว่าพังตรงไหน ไม่ใช่แค่ assert เปล่า ๆ"""
    assert not app.exception, "\n".join(str(e) for e in app.exception)


def test_แท็บครบทุกอัน(app: AppTest) -> None:
    from app import TABS

    assert len(app.tabs) == len(TABS)


def test_แต่ละแท็บวาดอะไรออกมาจริง(app: AppTest) -> None:
    """กันกรณีที่ไม่ error แต่ทุกแท็บว่างเปล่า ซึ่งก็คือพังเหมือนกัน

    ไม่เช็กว่าแท็บไหนวาดอะไร เพราะผูกกับข้อมูลในเครื่องมากเกินไป
    เอาแค่ว่ามีทั้งตารางและตัวเลขโผล่ออกมา แปลว่า view ทำงานถึงปลายทาง
    """
    assert app.dataframe, "ไม่มีตารางเลยสักอัน"
    assert app.metric, "ไม่มีเมตริกเลยสักอัน"
