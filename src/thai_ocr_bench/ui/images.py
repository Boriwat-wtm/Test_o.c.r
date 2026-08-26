"""แท็บตรวจภาพ — ดูภาพที่ render ออกมาว่าตรงกับต้นฉบับไหม"""

from __future__ import annotations

import streamlit as st

from ..config import IMAGE_DIR
from ..render import PageInfo


def view_images(pages: list[PageInfo]) -> None:
    st.subheader("ตรวจภาพก่อนเริ่มวัดผล")
    st.caption(
        "ทุกหน้าต้องตั้งตรง ถ้ามีหน้าไหนตะแคงต้องแก้ก่อน "
        "เพราะภาพตะแคงจะทำให้ผลทั้งชุดพังแล้วสรุปผิดว่า engine อ่านไทยไม่ได้"
    )

    sideways = [p for p in pages if not p.portrait]
    with st.container(border=True):
        a, b, c = st.columns(3)
        a.metric("จำนวนหน้า", len(pages))
        b.metric("ตั้งตรง", len(pages) - len(sideways))
        c.metric("ตะแคง", len(sideways), delta=None if not sideways else "ต้องแก้")

    if sideways:
        st.error("หน้าที่ยังตะแคง: " + ", ".join(p.page_id for p in sideways))

    docs = sorted({p.doc_name for p in pages})
    top = st.columns([2.6, 1.2, 1.2])
    chosen = top[0].selectbox("เอกสาร", docs)
    subset = [p for p in pages if p.doc_name == chosen]

    per_row = top[1].selectbox("รูปต่อแถว", [3, 4, 6, 8], index=1)
    # ของเดิมตัดที่ 16 หน้าเงียบ ๆ ไม่บอกว่ายังมีต่อ เอกสาร 54 หน้าจึงเห็นไม่ถึง
    # หนึ่งในสามโดยไม่รู้ตัว ตอนนี้บอกจำนวนจริงและกดดูเพิ่มได้
    limit = top[2].selectbox("แสดงกี่หน้า", [16, 32, 64, "ทั้งหมด"], index=0)
    show = subset if limit == "ทั้งหมด" else subset[: int(limit)]

    st.caption(
        f"`/Rotate` = {subset[0].rotation}° · เอกสารนี้มี {len(subset)} หน้า · "
        f"แสดง {len(show)} หน้า"
    )
    cols = st.columns(per_row)
    for i, page in enumerate(show):
        image = IMAGE_DIR / f"{page.page_id}.png"
        if image.exists():
            with cols[i % per_row]:
                with st.container(border=True):
                    st.image(
                        str(image),
                        caption=f"หน้า {page.page_no} · {page.width}x{page.height}",
                        width="stretch",
                    )


