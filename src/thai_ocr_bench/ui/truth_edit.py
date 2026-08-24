"""แท็บทำเฉลย — พิมพ์เฉลยเทียบกับภาพจริงทีละหน้า"""

from __future__ import annotations

import streamlit as st

from ..config import IMAGE_DIR
from ..render import PageInfo
from ..truth import load as load_truth, upsert as save_truth
from .common import page_label

# ── หน้า 2 ทำเฉลย ────────────────────────────────────────────────────────
def view_truth(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ทำเฉลย")
    st.caption(
        "อ่านเทียบกับภาพจริงทุกบรรทัด ระบบซ่อนชื่อ engine ที่ใช้เป็นร่างไว้ "
        "เพื่อไม่ให้ตัวนั้นได้เปรียบตอนวัดผล"
    )

    truth = load_truth()
    labels = {page_label(p): p for p in pages}
    picked = labels[st.selectbox("หน้า", list(labels))]

    left, right = st.columns([1, 1])
    image = IMAGE_DIR / f"{picked.page_id}.png"
    if image.exists():
        with left:
            with st.container(border=True):
                st.image(str(image), use_container_width=True)

    existing = truth.get(picked.page_id)
    if existing:
        draft = existing.text
        source = "จาก text layer" if existing.source == "text_layer" else "พิมพ์เอง"
        state = "ตรวจแล้ว" if existing.reviewed else "ยังไม่ตรวจ"
        right.info(f"เฉลยเดิม: {source} · {state}")
    else:
        # ยังไม่มีเฉลย เอาผลของ engine ที่ยาวสุดมาเป็นร่างให้แก้
        candidates = [
            (len("\n".join(p.lines)), p.lines)
            for pages_of in results.values()
            if (p := pages_of.get(picked.page_id)) and p.ok
        ]
        draft = "\n".join(max(candidates)[1]) if candidates else ""
        if draft:
            right.warning("ยังไม่มีเฉลย — ด้านล่างเป็นร่างจาก OCR ต้องแก้ให้ตรงภาพ")

    edited = right.text_area("เฉลย (แก้ได้)", value=draft, height=460, key=picked.page_id)
    if right.button("บันทึกเฉลยหน้านี้", type="primary"):
        lines = [ln.strip() for ln in edited.splitlines() if ln.strip()]
        save_truth(picked.page_id, lines, source="manual", reviewed=True)
        st.success(f"บันทึกแล้ว {len(lines)} บรรทัด")
        st.rerun()


