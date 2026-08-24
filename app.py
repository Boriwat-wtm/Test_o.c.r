"""หน้าเว็บตรวจผล OCR — ไฟล์นี้ทำแค่ประกอบแท็บ

เนื้อของแต่ละแท็บอยู่ใน src/thai_ocr_bench/ui/ ไฟล์ละแท็บ
เดิมทุกอย่างกองอยู่ในไฟล์นี้ไฟล์เดียว 1,731 บรรทัด จนหาอะไรไม่เจอ

รัน:  .venv\\Scripts\\streamlit.exe run app.py
"""

from __future__ import annotations

import streamlit as st

from thai_ocr_bench import store
from thai_ocr_bench.thai_text import THAI_DIGITS
from thai_ocr_bench.truth import load as load_truth
from thai_ocr_bench.ui.common import cached_pages, drop_watermarks
from thai_ocr_bench.ui.compare import view_compare
from thai_ocr_bench.ui.history_view import view_history
from thai_ocr_bench.ui.images import view_images
from thai_ocr_bench.ui.markdown_view import view_markdown
from thai_ocr_bench.ui.rescue_view import view_rescue
from thai_ocr_bench.ui.scan import progress_banner, scan_panel
from thai_ocr_bench.ui.summary import view_summary
from thai_ocr_bench.ui.suspects import view_suspects
from thai_ocr_bench.ui.theme import CSS
from thai_ocr_bench.ui.truth_edit import view_truth

st.set_page_config(page_title="ตรวจผล OCR ภาษาไทย", layout="wide")

# ชื่อแท็บกับฟังก์ชันที่วาดมัน คู่กันไว้ตรงนี้ที่เดียว
# แยกเป็นสองลิสต์แล้วเคยพลาดมาก่อน — เพิ่มแท็บใหม่แต่ลืมขยับเลข index
# ของแท็บที่อยู่หลังมัน ทำให้ทุกแท็บถัดไปวาดผิดอัน
TABS: list[tuple[str, str]] = [
    ("🔍 เปรียบเทียบ", "compare"),
    ("⚠️ จุดน่าสงสัย", "suspects"),
    ("📊 สรุปผล", "summary"),
    ("✏️ ทำเฉลย", "truth"),
    ("🖼️ ตรวจภาพ", "images"),
    ("🔎 อ่านซ้ำแบบซูม", "rescue"),
    ("📝 markdown", "markdown"),
    ("🧾 ประวัติการรัน", "history"),
]


def sidebar(pages: list, results: dict, truth: dict) -> None:
    """แถบซ้าย — ตัวเลขของชุดข้อมูลกับปุ่มสั่งสแกน"""
    # เมตริกแถวเดียวสามช่อง สี่ช่องสองแถวสูงเกินไปสำหรับแถบแคบ ๆ
    # ส่วนที่เหลือเป็นตัวเลขอ้างอิง ยัดเป็น caption บรรทัดเดียวพอ
    st.subheader("ชุดข้อมูล", divider="gray")
    c1, c2, c3 = st.columns(3)
    c1.metric("หน้า", len(pages))
    c2.metric("มีเฉลย", len(truth))
    c3.metric("engine", len(results))

    digits_in_truth = sum(t.text.count(d) for t in truth.values() for d in THAI_DIGITS)
    st.caption(
        f"เลขไทยในเฉลย {digits_in_truth:,} ตัว · "
        f"ยังไม่มีเฉลย {len(pages) - len(truth)} หน้า"
    )
    if not results:
        st.warning("ยังไม่มีผล OCR — กดสแกนด้านล่าง")

    scan_panel(pages, results)


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("ตรวจผล OCR ภาษาไทย")
    st.caption(
        "เทียบผล OCR แต่ละตัวกับเฉลยทีละบรรทัด — สั่งสแกนได้จากแถบซ้าย "
        "ตัวรันเป็นคนละโปรเซส ปิดหน้านี้ระหว่างรันได้"
    )

    pages = cached_pages()
    if not pages:
        st.error("ยังไม่มีภาพ — รัน `render_pages.py` ก่อน")
        return

    results = drop_watermarks(store.load())
    truth = load_truth()

    with st.sidebar:
        sidebar(pages, results, truth)

    progress_banner(len(pages))

    # st.tabs() รันเนื้อหาทุกแท็บทุกรอบ แค่ซ่อนด้วย CSS — ไม่ใช่ lazy
    # แท็บที่คำนวณหนักจึงต้องแคชเอง ห้ามหวังว่าไม่เปิดแล้วจะไม่ทำงาน
    tabs = st.tabs([label for label, _ in TABS])
    draw = {
        "compare": lambda: view_compare(pages, results),
        "suspects": lambda: view_suspects(pages, results),
        "summary": lambda: view_summary(pages, results),
        "truth": lambda: view_truth(pages, results),
        "images": lambda: view_images(pages),
        "rescue": lambda: view_rescue(pages, results),
        "markdown": lambda: view_markdown(pages, results),
        "history": view_history,
    }
    for tab, (_, key) in zip(tabs, TABS):
        with tab:
            draw[key]()


if __name__ == "__main__":
    main()
