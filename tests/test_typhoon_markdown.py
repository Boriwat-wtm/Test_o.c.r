"""เทสต์การถอด markdown ของ Typhoon API — ความเสี่ยงคือ "ตัดเนื้อหาจริงทิ้ง"

API คืนข้อความเป็น markdown เราจึงต้องถอดสัญลักษณ์จัดรูปแบบออกก่อนเทียบกับเฉลย
แต่เอกสารราชการใช้อักขระชุดเดียวกันเป็นเนื้อหาด้วย (* กับ ** เป็นตัวโยงเชิงอรรถ)
ถ้าตัดเหมารวมจะกลายเป็นลงโทษ engine ที่อ่านถูก เพราะขั้นตอนหลังบ้านของเราเอง
เทสต์จึงคุมสองด้าน ต้องตัดของที่เป็นรูปแบบจริง และต้องไม่แตะของที่เป็นเนื้อหา
"""

from __future__ import annotations

from thai_ocr_bench.engines.typhoon_api import _strip_markdown


def test_เชิงอรรถดอกจันคู่ต้องไม่หาย() -> None:
    """เคสที่เป็นเหตุให้แก้ — หน้าคำสั่งกรมที่ดินใช้ * กับ ** เป็นตัวโยงหมายเหตุ"""
    line = "** (ที่ดินแบบ ๓๕) คือ (ท.ด. ๓๕) เดิมซึ่งได้ยุบเลิก"
    assert _strip_markdown(line) == line


def test_เชิงอรรถดอกจันเดี่ยวต้องไม่หาย() -> None:
    line = "* (ที่ดินแบบ ๓๔) (ท.ด. ๓๔)"
    assert _strip_markdown(line) == line


def test_ตัวหนาจริงยังถูกถอด() -> None:
    assert _strip_markdown("**ตัวหนา** ตามหลัง") == "ตัวหนา ตามหลัง"
    assert _strip_markdown("__ขีดล่าง__ ตามหลัง") == "ขีดล่าง ตามหลัง"


def test_หัวข้อถอดเฉพาะที่มีช่องว่างตามหลัง() -> None:
    assert _strip_markdown("## หัวข้อ") == "หัวข้อ"
    # ไม่มีช่องว่าง = ไม่ใช่หัวข้อ markdown เป็นอักขระในเนื้อหา
    assert _strip_markdown("#๑๒๓ เลขที่") == "#๑๒๓ เลขที่"


def test_แท็กโครงสร้างถูกถอดแต่เก็บข้อความไว้() -> None:
    assert _strip_markdown("<page_number>- ๘ -</page_number>") == "- ๘ -"


def test_เส้นคั่นกับเส้นตารางถูกตัดทิ้ง() -> None:
    assert _strip_markdown("---") == ""
    assert _strip_markdown("|---|---|") == ""


def test_แถวตารางถูกแตกเป็นข้อความ() -> None:
    assert _strip_markdown("| ก | ข |") == "ก ข"
