"""แท็บทำเฉลย — พิมพ์เฉลยเทียบกับภาพจริงทีละหน้า"""

from __future__ import annotations

import streamlit as st

from ..config import IMAGE_DIR
from ..render import PageInfo
from ..truth import load as load_truth, upsert as save_truth


def view_truth(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ทำเฉลย")
    st.caption(
        "อ่านเทียบกับภาพจริงทุกบรรทัด ระบบซ่อนชื่อ engine ที่ใช้เป็นร่างไว้ "
        "เพื่อไม่ให้ตัวนั้นได้เปรียบตอนวัดผล"
    )

    truth = load_truth()
    done = sum(1 for p in pages if p.page_id in truth)
    st.progress(
        done / len(pages) if pages else 0,
        text=f"มีเฉลยแล้ว {done} จาก {len(pages)} หน้า",
    )

    # แยกช่องเอกสารกับหน้าออกจากกัน เหมือนแท็บเปรียบเทียบ
    # ของเดิมเป็นช่องเดียวรวม 97 หน้า ทุกบรรทัดขึ้นต้นด้วยชื่อเอกสารซ้ำกัน
    # ต่างแค่เลขหน้าท้ายสุด หาหน้าที่ต้องการยาก
    docs = sorted({p.doc_name for p in pages})
    top = st.columns([2.4, 1.4, 1.2])
    doc = top[0].selectbox("เอกสาร", docs, key="truth_doc")
    subset = [p for p in pages if p.doc_name == doc]

    only_todo = top[2].toggle(
        "เฉพาะที่ยังไม่มีเฉลย",
        value=False,
        help="เปิดไว้เวลาไล่ทำเฉลยให้ครบ จะได้ไม่ต้องข้ามหน้าที่ทำแล้วเอง",
    )
    pool = [p for p in subset if p.page_id not in truth] if only_todo else subset
    if not pool:
        st.success(f"เอกสารนี้มีเฉลยครบทุกหน้าแล้ว ({len(subset)} หน้า)")
        return

    labels = {
        f"หน้า {p.page_no}" + ("" if p.page_id in truth else "  ·  ยังไม่มีเฉลย"): p
        for p in pool
    }
    picked = labels[top[1].selectbox("หน้า", list(labels), key="truth_page")]

    left, right = st.columns([1, 1])
    image = IMAGE_DIR / f"{picked.page_id}.png"
    if image.exists():
        with left:
            with st.container(border=True):
                st.image(str(image), width="stretch")

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

    edited = right.text_area(
        "เฉลย (แก้ได้)", value=draft, height=460, key=picked.page_id
    )
    right.caption(
        f"{len([ln for ln in edited.splitlines() if ln.strip()])} บรรทัด · "
        f"{len(edited)} ตัวอักษร"
    )
    if right.button("บันทึกเฉลยหน้านี้", type="primary"):
        lines = [ln.strip() for ln in edited.splitlines() if ln.strip()]
        save_truth(picked.page_id, lines, source="manual", reviewed=True)
        st.success(f"บันทึกแล้ว {len(lines)} บรรทัด")
        st.rerun()
