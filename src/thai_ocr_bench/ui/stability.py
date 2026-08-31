"""แท็บวัดความนิ่ง — ส่งภาพเดิมให้ typhoon-api อ่านซ้ำหลายรอบ แล้วดูว่าตอบตรงกันไหม

ต่างจากแท็บ "อ่านซ้ำแบบซูม" ตรงคำถามที่ถาม
  อ่านซ้ำแบบซูม  ถาม "ครอปแล้วขยายช่วยให้อ่านถูกขึ้นไหม"   เทียบก่อน-หลัง
  วัดความนิ่ง    ถาม "engine มั่นใจกับคำตอบตัวเองแค่ไหน"   เทียบรอบต่อรอบ

ทำไมต้องเป็นสัญญาณจากตัว engine เอง — วัดแล้วสองวิธีที่พึ่งคนอื่นใช้ไม่ได้
  ค่า confidence ของ engine คลาสสิก  บรรทัดผิด 0.939 บรรทัดถูก 0.943 แยกไม่ออก
  โหวตข้าม engine เรื่องเลขไทย        ช่วยได้ 14% เพราะตัวอื่นอ่านเลขไทยถูกแค่ 43-56%

จำกัดเฉพาะตระกูล typhoon-api เพราะเป็นตัวเดียวที่ควบคุมการสุ่มได้และไม่กินการ์ดจอ
"""

from __future__ import annotations

import json

import streamlit as st

from ..config import IMAGE_DIR, RESULTS_DIR
from ..render import PageInfo
from ..rescue_crop import ZOOM
from ..thai_text import normalize
from .common import page_label, rescue_crop_uri
from .rescue_view import start_rescue

# ตัวที่หน้านี้รองรับ — ต้องมี read_variants() และไม่กินการ์ดจอ
API_ENGINES = ("typhoon-api", "typhoon-api-num", "typhoon-api+clean", "typhoon-api-num+clean")


def _load(engine: str) -> list[dict]:
    """อ่านผลของ engine ที่ระบุจากแฟ้มแยกตาม engine

    ไม่อ่าน rescue.json เพราะแฟ้มนั้นเก็บได้ทีละตัว รันตัวถัดไปแล้วทับ
    """
    path = RESULTS_DIR / f"rescue_{engine.replace('+', '_').replace('/', '_')}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in data.get("items", []) if r.get("agree") is not None]


def _diff_summary(variants: list[str]) -> str:
    """บอกสั้น ๆ ว่าแต่ละรอบต่างกันแค่ไหน — กี่แบบจากกี่รอบ"""
    forms = {normalize(v) for v in variants}
    return f"{len(variants)} รอบ ได้ {len(forms)} แบบ"


def _run_panel() -> None:
    """ปุ่มสั่งรัน — วางไว้บนสุดเพราะหน้านี้ว่างเปล่าจนกว่าจะรัน"""
    with st.expander("สั่งวัดความนิ่ง", expanded=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        engine = c1.selectbox("engine", API_ENGINES, key="stab_engine")
        samples = c2.number_input(
            "อ่านกี่รอบ", min_value=2, max_value=7, value=3, key="stab_n",
            help="ยิ่งมากยิ่งจับความไม่นิ่งได้ละเอียด แต่กินโควตา API เป็นเท่าตัว",
        )
        limit = c3.number_input(
            "จำกัดกี่จุด", min_value=0, max_value=500, value=0, step=10, key="stab_lim",
            help="0 = ทุกจุด · ใส่เลขไว้ตอนอยากลองก่อน",
        )
        st.caption(
            f"ยิง API ประมาณ (จำนวนจุด × {samples}) ครั้ง มี throttle 3.1 วินาทีต่อครั้ง "
            "ตัวรันแยกโปรเซส ปิดหน้านี้ระหว่างรันได้"
        )
        if st.button("เริ่มวัด", type="primary", key="stab_go"):
            start_rescue(engine, int(limit) or None, samples=int(samples))
            st.success("สั่งรันแล้ว — กดปุ่มโหลดผลใหม่ด้านล่างเป็นระยะ")


def view_stability(pages: list[PageInfo], results: dict) -> None:
    st.subheader("วัดความนิ่ง")
    st.caption(
        "ส่งภาพครอปใบเดิมให้ engine อ่านซ้ำหลายรอบแบบสุ่ม — "
        "รอบที่ตอบไม่ตรงกันคือจุดที่ engine เองก็ไม่มั่นใจ ควรให้คนดูภาพ"
    )

    _run_panel()

    engine = st.selectbox("ดูผลของ", API_ENGINES, key="stab_view")
    items = _load(engine)

    if not items:
        st.info(
            f"ยังไม่มีผลของ `{engine}` — กางกล่อง **สั่งวัดความนิ่ง** ด้านบนแล้วกดเริ่มวัด\n\n"
            "หรือรันจากเทอร์มินัล:\n"
            f"`.venv/Scripts/python.exe rescue.py --engine {engine} --samples 3`"
        )
        if st.button("โหลดผลใหม่", key="stab_reload_empty"):
            st.rerun()
        return

    unstable = [r for r in items if r["agree"] is False]
    steady = [r for r in items if r["agree"] is True]
    n_samples = max((len(r.get("variants") or []) for r in items), default=0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("จุดที่วัด", len(items))
    c2.metric("นิ่ง", len(steady), "ตอบตรงกันทุกรอบ", delta_color="off")
    c3.metric("ไม่นิ่ง", len(unstable), "ต้องให้คนดู", delta_color="off")
    c4.metric(
        "อัตราไม่นิ่ง",
        f"{len(unstable) / len(items):.0%}" if items else "-",
        f"อ่านรอบละ {n_samples} ครั้ง",
        delta_color="off",
    )

    st.caption(
        "ตัวเลขนี้ไม่ใช่อัตราการอ่านผิด — เป็นอัตราที่ engine ตอบไม่เหมือนเดิม "
        "จุดที่นิ่งอาจผิดได้ถ้ามันมั่นใจผิด ๆ และจุดที่ไม่นิ่งบางรอบก็ตอบถูก"
    )
    st.divider()

    if not unstable:
        st.success(
            f"ทุกจุดที่วัดตอบตรงกันทุกรอบ — ไม่ได้แปลว่าอ่านถูกหมด "
            f"แปลว่า {engine} ไม่ลังเลตรงจุดที่เราหยิบมาวัด"
        )
        return

    st.markdown(f"#### {len(unstable)} จุดที่ไม่นิ่ง")
    byid = {p.page_id: p for p in pages}

    for i, r in enumerate(unstable):
        page = byid.get(r["page_id"])
        label = page_label(page) if page else r["page_id"]
        variants = r.get("variants") or []
        head = f"{label} · บรรทัดที่ {r['grid_line'] + 1} · {_diff_summary(variants)}"

        with st.expander(head, expanded=(i == 0)):
            if r.get("box"):
                uri = rescue_crop_uri(
                    str(IMAGE_DIR / f"{r['page_id']}.png"), tuple(r["box"])
                )
                if uri:
                    st.markdown(
                        f'<img src="{uri}" style="width:100%;border-radius:.5rem;'
                        f'border:1px solid var(--border)" alt="บรรทัดที่วัดความนิ่ง">',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"ภาพที่ engine เห็นทุกรอบ — ครอปแล้วขยาย {ZOOM} เท่า")

            # เรียงตามความถี่ ไม่ใช่ตามลำดับรอบ — คำตอบที่ซ้ำบ่อยขึ้นก่อนอ่านง่ายกว่า
            # แต่ห้ามสรุปว่าเสียงข้างมากถูก เคสจริงที่เจอเสียงข้างมากผิด 2:1
            groups: dict[str, list[int]] = {}
            for j, v in enumerate(variants, 1):
                groups.setdefault(normalize(v), []).append(j)
            order = sorted(groups.items(), key=lambda kv: -len(kv[1]))

            for form, rounds in order:
                raw = variants[rounds[0] - 1]
                st.markdown(
                    f'<div class="lab">รอบ {", ".join(map(str, rounds))} '
                    f'({len(rounds)}/{len(variants)})</div>',
                    unsafe_allow_html=True,
                )
                st.code(raw or "(ว่าง)")

            st.caption(
                "อย่าเลือกคำตอบจากจำนวนรอบที่ซ้ำ — วัดแล้วพบเคสที่เสียงข้างมาก 2:1 เป็นฝ่ายผิด "
                "ต้องเทียบกับภาพด้านบนเอง"
            )

    if st.button("โหลดผลใหม่", key="stab_reload"):
        st.rerun()
