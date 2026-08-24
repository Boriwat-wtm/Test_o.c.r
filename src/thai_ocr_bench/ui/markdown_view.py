"""แท็บส่งออก markdown — เอาผล OCR ออกมาให้คนแก้ต่อแล้วเก็บไว้"""

from __future__ import annotations

import streamlit as st

from .. import markdown_out
from ..render import PageInfo

def view_markdown(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ส่งออก markdown")
    st.caption(
        "เอาผลที่ OCR อ่านได้ออกมาเป็นไฟล์ markdown ทั้งเอกสาร แก้ในช่องนี้ได้เลย "
        "กดบันทึกแล้วไฟล์จะไปอยู่ในโฟลเดอร์ exports/ ครั้งต่อไปจะเปิดฉบับที่แก้แล้วขึ้นมาให้"
    )
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    docs = sorted({p.doc_name for p in pages})
    top = st.columns([2.4, 1.6])
    doc = top[0].selectbox("เอกสาร", docs, key="md_doc")
    subset = sorted(
        [p for p in pages if p.doc_name == doc], key=lambda p: p.page_no
    )

    # เอาเฉพาะ engine ที่อ่านเอกสารนี้ไว้จริง ไม่ใช่ทุกตัวที่เคยรันอะไรก็ได้
    # ไม่งั้นเลือกไปแล้วได้ไฟล์เปล่าโดยไม่รู้ว่าทำไม
    ids = {p.page_id for p in subset}
    usable = sorted(
        name for name, per_page in results.items()
        if any(pid in per_page and per_page[pid].ok for pid in ids)
    )
    if not usable:
        st.warning("ยังไม่มี engine ตัวไหนอ่านเอกสารนี้")
        return
    engine = top[1].selectbox("ผลของ engine", usable, key="md_engine")

    per_page = results[engine]
    built = markdown_out.build(
        doc,
        engine,
        [
            (p.page_no, p.page_id, per_page[p.page_id].lines)
            for p in subset
            if p.page_id in per_page and per_page[p.page_id].ok
        ],
    )
    saved = markdown_out.load(doc, engine)
    path = markdown_out.path_for(doc, engine)

    if saved:
        st.success(f"เปิดฉบับที่แก้ไว้แล้ว · {path}")
    else:
        st.info("ยังไม่เคยบันทึกเอกสารนี้ — ด้านล่างเป็นผลดิบจาก OCR")

    # ผูก key กับเอกสาร+engine ไม่งั้นสลับตัวเลือกแล้ว Streamlit จำค่าเดิมไว้
    # ผู้ใช้จะเห็นเนื้อหาของอันก่อนหน้าค้างอยู่แล้วเผลอกดบันทึกทับ
    edited = st.text_area(
        "markdown (แก้ได้)",
        value=saved or built,
        height=560,
        key=f"md_text·{doc}·{engine}",
    )

    act = st.columns([1, 1, 3])
    if act[0].button("บันทึก", type="primary", key="md_save"):
        written = markdown_out.save(doc, engine, edited)
        st.success(f"บันทึกแล้ว · {written}")
    if saved and act[1].button("ย้อนกลับเป็นผลดิบ", key="md_reset"):
        # ลบไฟล์ที่แก้ไว้ทิ้ง แล้วให้รอบหน้าไปสร้างใหม่จากผลดิบ
        path.unlink(missing_ok=True)
        st.session_state.pop(f"md_text·{doc}·{engine}", None)
        st.rerun()

    act[2].download_button(
        "ดาวน์โหลด .md",
        data=edited.encode("utf-8"),
        file_name=path.name,
        mime="text/markdown",
        key="md_download",
    )

    with st.expander("ดูตัวอย่างที่ render แล้ว"):
        st.markdown(edited)


