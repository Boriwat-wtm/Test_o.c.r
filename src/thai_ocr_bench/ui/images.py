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
    chosen = st.selectbox("เอกสาร", docs)
    subset = [p for p in pages if p.doc_name == chosen]

    st.caption(f"`/Rotate` = {subset[0].rotation}° · {len(subset)} หน้า")
    cols = st.columns(4)
    for i, page in enumerate(subset[:16]):
        image = IMAGE_DIR / f"{page.page_id}.png"
        if image.exists():
            with cols[i % 4]:
                with st.container(border=True):
                    st.image(
                        str(image),
                        caption=f"หน้า {page.page_no} · {page.width}x{page.height}",
                        use_container_width=True,
                    )


