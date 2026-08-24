"""แท็บอ่านซ้ำแบบซูม — ครอปเฉพาะบรรทัดที่น่าสงสัยแล้วให้ engine อ่านใหม่"""

from __future__ import annotations

import json
import subprocess
import sys

import streamlit as st

from .. import history
from ..config import IMAGE_DIR, RESULTS_DIR, ROOT
from ..render import PageInfo
from .common import _crop, page_label

def start_rescue(engine: str, limit: int | None) -> None:
    """สั่ง rescue.py เป็นคนละโปรเซส แบบเดียวกับปุ่มสแกน

    ต้องแยกโปรเซสเพราะการอ่านซ้ำยิง API ทีละจุดโดยมี throttle 3.1 วินาที
    ถ้ารันในโปรเซสของหน้าเว็บจะบล็อกจนหน้าหมุนค้างเป็นนาที
    """
    cmd = [sys.executable, str(ROOT / "rescue.py"), "--engine", engine]
    if limit:
        cmd += ["--limit", str(limit)]

    log = RESULTS_DIR / "rescue.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    handle.write(f"\n{'=' * 70}\nเริ่มอ่านซ้ำ {history.now_iso()} · engine {engine}\n")
    handle.flush()
    subprocess.Popen(
        cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def rescue_controls(results: dict) -> None:
    """แผงสั่งอ่านซ้ำ — วางไว้บนสุดของแท็บ ไม่ต้องออกไปพิมพ์คำสั่งเอง"""
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1.2, 1.4])
        names = sorted(results)
        if not names:
            st.caption("ยังไม่มีผล OCR ให้อ่านซ้ำ — สแกนก่อน")
            return
        # ตัวที่แม่นสุดคุ้มสุดที่จะอ่านซ้ำ เพราะจุดที่มันยังผิดคือจุดที่ยากจริง
        default = next((i for i, n in enumerate(names) if "num" in n), 0)
        engine = c1.selectbox("engine ที่จะให้อ่านซ้ำ", names, index=default)
        limit = c2.number_input("จำกัดจุด", min_value=0, max_value=999, value=0,
                                help="0 = ไม่จำกัด ใส่เลขไว้ลองก่อนได้")
        c3.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        if c3.button("เริ่มอ่านซ้ำ", type="primary", use_container_width=True):
            start_rescue(engine, int(limit) or None)
            st.success("สั่งแล้ว — กดโหลดใหม่อีกครั้งเมื่อรันเสร็จ")


def view_rescue(pages: list[PageInfo], results: dict) -> None:
    st.subheader("จุดที่อ่านซ้ำแบบซูม")
    st.caption(
        "จุดที่ตัวคัดสงสัยว่าอ่านผิด ถูกครอปออกมาขยาย 4 เท่าแล้วส่งให้อ่านใหม่ "
        "ผลอยู่ที่นี่เพื่อให้ตัดสินทีละจุด ไม่ได้เขียนทับผลเดิมอัตโนมัติ"
    )

    rescue_controls(results)

    path = RESULTS_DIR / "rescue.json"
    if not path.exists():
        st.info("ยังไม่มีผลอ่านซ้ำ — เลือก engine ด้านบนแล้วกดเริ่มอ่านซ้ำ")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    engine = data.get("engine", "?")
    if not items:
        st.info("ไฟล์มีอยู่แต่ไม่มีจุดไหนถูกอ่านซ้ำ")
        return

    changed = [r for r in items if r.get("changed")]
    failed = [r for r in items if r.get("error")]
    # agree มีเฉพาะตอนรันด้วย --samples N (อ่านซ้ำหลายรอบแบบสุ่ม)
    # ผลรอบเก่าที่รันก่อนมีฟีเจอร์นี้จะไม่มีคีย์นี้เลย จึงต้องเช็กว่ามีจริงก่อน
    unstable = [r for r in items if r.get("agree") is False]
    has_variants = any(r.get("agree") is not None for r in items)

    cols = st.columns(4 if has_variants else 3)
    cols[0].metric("จุดที่อ่านซ้ำ", len(items))
    cols[1].metric("ข้อความเปลี่ยน", len(changed))
    cols[2].metric("อ่านไม่สำเร็จ", len(failed))
    if has_variants:
        cols[3].metric(
            "ไม่มั่นใจ", len(unstable), "ตอบไม่ตรงกันแต่ละรอบ", delta_color="off"
        )
    st.caption(f"engine ที่ใช้อ่านซ้ำ: `{engine}`")

    choices = ["เฉพาะที่ข้อความเปลี่ยน", "ทั้งหมด"]
    if has_variants:
        choices.insert(1, "เฉพาะที่ไม่มั่นใจ")
    mode = st.radio("แสดง", choices, horizontal=True, label_visibility="collapsed")
    shown = {
        "เฉพาะที่ข้อความเปลี่ยน": changed,
        "เฉพาะที่ไม่มั่นใจ": unstable,
        "ทั้งหมด": items,
    }[mode]

    if not has_variants:
        st.caption(
            "อยากรู้ว่าจุดไหน engine เองก็ไม่มั่นใจ ให้รันด้วย "
            "`rescue.py --engine <engine> --samples 3` — จะอ่านซ้ำหลายรอบแบบสุ่ม "
            "แล้วเทียบว่าตอบตรงกันไหม ใช้ได้กับตระกูล typhoon ทั้ง local และ API "
            "(ฝั่ง API กินโควตา ๓ เท่า)"
        )

    if not shown:
        st.success("ไม่มีจุดที่เข้าเงื่อนไขนี้ — ผลเดิมน่าจะถูกอยู่แล้ว")
        return

    byid = {p.page_id: p for p in pages}
    for i, r in enumerate(shown):
        page = byid.get(r["page_id"])
        label = page_label(page) if page else r["page_id"]
        head = f"{label} · บรรทัดที่ {r['grid_line'] + 1}"
        if r.get("agree") is False:
            head = "⚠️ " + head + " · ไม่มั่นใจ"
        with st.expander(head, expanded=(i == 0)):
            # ครอปด้วยกรอบเดียวกับที่ rescue ใช้ จะได้เห็นสิ่งที่ engine เห็นตอนอ่านซ้ำ
            img = _crop(str(IMAGE_DIR / f"{r['page_id']}.png"), tuple(r["box"]), pad=24)
            if img:
                st.markdown(
                    f'<img src="{img}" style="width:100%;border:1px solid #E4E6EC;'
                    f'border-radius:8px" alt="ภาพบรรทัดที่อ่านซ้ำ">',
                    unsafe_allow_html=True,
                )
            a, b = st.columns(2)
            a.markdown("**เดิม** (อ่านรวมทั้งหน้า)")
            a.code(r["before"] or "(ว่าง)")
            b.markdown("**อ่านซ้ำ** (ครอป · ขยาย 4 เท่า)")
            b.code(r["after"] or "(ว่าง)")

            # อ่านซ้ำหลายรอบแบบสุ่มแล้วตอบไม่ตรงกัน = engine เองก็ไม่มั่นใจตรงนี้
            # เป็นสัญญาณที่ได้จากตัว engine ล้วน ๆ ไม่ต้องพึ่ง engine อื่นมาเทียบ
            variants = r.get("variants") or []
            if len(variants) > 1:
                if r.get("agree") is False:
                    st.warning(
                        f"อ่านซ้ำ {len(variants)} รอบได้คำตอบไม่ตรงกัน — "
                        "จุดนี้ควรให้คนดูภาพเอง"
                    )
                    for j, v in enumerate(variants, 1):
                        st.code(f"รอบ {j}: {v}")
                else:
                    st.success(f"อ่านซ้ำ {len(variants)} รอบได้เหมือนกันทุกรอบ")

            if r.get("error"):
                st.error(f"อ่านซ้ำไม่สำเร็จ: {r['error']}")

    if st.button("โหลดผลอ่านซ้ำใหม่"):
        st.rerun()
    st.caption(
        "ยังไม่มีปุ่มรับผลอ่านซ้ำเข้าไปแทนที่ของเดิม เพราะข้อความเดิมเป็นส่วนที่หั่นตามกริด "
        "ซึ่งบางครั้งกินยาวกว่าบรรทัดจริงในภาพ แทนที่ตรง ๆ แล้ววัดได้ว่าทำข้อความหาย"
    )


