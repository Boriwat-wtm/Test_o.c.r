"""แท็บตรวจงาน — หน้าที่ใช้ทำงานจริง ชี้ว่าตรงไหนต้องดู พร้อมภาพตรงจุดนั้น

รวมสองสัญญาณที่วัดแล้วว่าคุ้มที่สุดเข้าด้วยกัน (ดูเหตุผลเต็มใน review.py)
  ตัวเลข       ดู 2.8% ของหน้า ครอบคลุมความผิด 45%
  ความไม่นิ่ง   จับของที่โมเดลแต่งเอง ซึ่งตัวเลขจับไม่ได้

ต่างจากแท็บ "จุดน่าสงสัย" ตรงที่ไม่พึ่ง engine อื่นมาตัดสินข้อความ
วัดแล้วการโหวตข้าม engine จับผิดได้แค่ 2% เพราะเอาตัวที่แม่นน้อยกว่า
มาตัดสินตัวที่แม่นที่สุด ตรงนี้ engine อื่นมีหน้าที่เดียวคือบอกพิกัด
"""

from __future__ import annotations

import html
import json

import streamlit as st

from .. import markdown_out, review
from ..config import IMAGE_DIR, CLEAN_IMAGE_DIR, RESULTS_DIR
from ..render import PageInfo
from ..suspect import thai_digit_by_document
from .common import cached_image, rescue_crop_uri, short_doc

# ตัวที่คืนพิกัดข้อความ เรียงตามความน่าเชื่อถือของกรอบที่วัดมา
_DONORS = ("tesseract-tha", "paddle-th", "easyocr-th")

_TONE = {
    "digit": ("num", "ตัวเลข"),
    "mixed": ("bad", "ผิดแน่"),
    "shaky": ("warn", "ไม่นิ่ง"),
}


def _donor_for(engine: str, results: dict, page_id: str) -> str | None:
    """หา engine ที่คืนพิกัด และอ่านภาพชุดเดียวกับตัวหลัก

    +clean ต้องยืมจาก +clean เท่านั้น ภาพคนละชุดพิกัดคนละที่
    """
    suffix = "+clean" if engine.endswith("+clean") else ""
    for base in _DONORS:
        name = base + suffix
        page = results.get(name, {}).get(page_id)
        if page and page.ok and any(page.boxes):
            return name
    return None


def _shaky_for(engine: str, page_id: str) -> list[bool] | None:
    """ผลวัดความนิ่งของหน้านี้ ถ้าเคยรันไว้"""
    name = engine.replace("+", "_").replace("/", "_")
    path = RESULTS_DIR / f"stability_{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    page = data.get("pages", {}).get(page_id)
    return [not m["stable"] for m in page["lines"]] if page else None


def _render(row: review.ReviewLine) -> str:
    """ระบายสีเฉพาะช่วงที่ต้องดู ส่วนที่เหลือปล่อยไว้

    ความไม่นิ่งครอบทั้งบรรทัดจึงวาดเป็นพื้นหลังจาง ๆ แล้ววาดตัวเลขทับ
    ไม่งั้นทั้งบรรทัดแดงจนมองไม่เห็นว่าตัวเลขอยู่ตรงไหน
    """
    spans = [m for m in row.marks if m.kind != "shaky"]
    body, cursor = [], 0
    for m in sorted(spans, key=lambda m: m.start):
        if m.start < cursor:
            continue
        body.append(html.escape(row.text[cursor : m.start]))
        cls = "wrong" if m.kind == "mixed" else "num"
        body.append(
            f'<span class="{cls}" data-tip="{html.escape(m.note)}">'
            f"{html.escape(row.text[m.start : m.end])}</span>"
        )
        cursor = m.end
    body.append(html.escape(row.text[cursor:]))

    inner = "".join(body)
    if any(m.kind == "shaky" for m in row.marks):
        inner = f'<span class="shaky-line">{inner}</span>'
    return f'<div class="ln">{inner}</div>'


def _focus_mode(
    picked, engine: str, rows: list, img: Path, saved: str | None, lines: list[str]
) -> None:
    """ตรวจทีละจุด — ภาพใหญ่ ข้อความเดียว ปุ่มไม่กี่ปุ่ม

    ทำไมไม่แสดงเป็นรายการยาวให้เลื่อนดู — งานนี้คือ "ดูจุดนี้ เทียบภาพ
    แก้ถ้าผิด ไปจุดถัดไป" ซ้ำไปเรื่อย ๆ การเห็นทุกจุดพร้อมกันไม่ได้ช่วย
    แต่ทำให้ต้องเลื่อนหาเองว่าดูถึงไหนแล้ว และภาพครอปที่ซ่อนใต้ปุ่ม
    ต้องกดเปิดทุกบรรทัด ทั้งที่มันคือสิ่งเดียวที่ต้องดูจริง

    จำตำแหน่งที่ดูถึงไว้แยกตามหน้า สลับหน้าไปมาแล้วกลับมายังอยู่ที่เดิม
    (ไม่รอดข้ามการรีสตาร์ทเซิร์ฟเวอร์ ซึ่งยอมรับได้สำหรับงานตรวจทีละรอบ)
    """
    todo = [r for r in rows if r.needs_check]
    if not todo:
        st.success("หน้านี้ไม่มีจุดที่ต้องตรวจ — ไม่ได้แปลว่าอ่านถูกหมด")
        return

    key = f"rv_at|{picked.page_id}|{engine}"
    at = min(st.session_state.get(key, 0), len(todo) - 1)
    row = todo[at]

    st.progress((at + 1) / len(todo), text=f"จุดที่ {at + 1} จาก {len(todo)} ในหน้านี้")

    # ภาพครอปกางเต็มความกว้าง เป็นสิ่งที่คนต้องดูจริง ไม่ควรต้องกดเปิด
    if row.box:
        uri = rescue_crop_uri(str(img), tuple(row.box))
        if uri:
            st.markdown(
                f'<img src="{uri}" style="width:100%;border-radius:.5rem;'
                f'border:1px solid var(--border)">',
                unsafe_allow_html=True,
            )
    else:
        st.warning(
            "ยืมพิกัดบรรทัดนี้ไม่ได้ จึงไม่มีภาพครอป — "
            "สั่งสแกน tesseract กับหน้านี้ก่อนถึงจะมีภาพให้เทียบ"
        )

    tags = " · ".join(dict.fromkeys(_TONE[m.kind][1] for m in row.marks))
    st.markdown(
        f'<div class="lab">บรรทัด {row.index + 1} · {tags}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(_render(row), unsafe_allow_html=True)

    fixed = st.text_input(
        "แก้ตรงนี้ถ้าไม่ตรงกับภาพ",
        value=row.text,
        key=f"rv_fix|{picked.page_id}|{engine}|{row.index}",
    )

    changed = fixed.strip() != row.text.strip()
    last = at >= len(todo) - 1
    b = st.columns([1.0, 1.5, 1.1, 1.8])

    if b[0].button("ย้อนกลับ", disabled=at == 0, key=f"rv_prev|{picked.page_id}"):
        st.session_state[key] = at - 1
        st.rerun()

    if changed:
        label = "บันทึกแล้วไปต่อ"
    elif last:
        label = "ถูกแล้ว จบหน้านี้"
    else:
        label = "ถูกแล้ว ไปต่อ"
    if b[1].button(label, type="primary", key=f"rv_next|{picked.page_id}"):
        if changed:
            merged = list(lines)
            merged[row.index] = fixed
            markdown_out.save_page(picked.page_id, engine, "\n".join(merged))
        st.session_state[key] = min(at + 1, len(todo) - 1)
        st.rerun()

    if b[2].button("ข้ามไปก่อน", disabled=last, key=f"rv_skip|{picked.page_id}"):
        st.session_state[key] = at + 1
        st.rerun()

    if saved is not None:
        with b[3]:
            if st.button("ล้างที่แก้ไว้", key=f"rv_reset|{picked.page_id}"):
                markdown_out.clear_page(picked.page_id, engine)
                st.rerun()


def _page_mode(picked, engine: str, rows: list, img: Path, s: dict, donor) -> None:
    """ดูทั้งหน้ารวดเดียว — ไว้กวาดตาดูภาพรวม ไม่ใช่ไว้แก้ทีละจุด"""
    note = (
        f"ยืมพิกัดจาก `{donor}` — ได้ {s['with_box']}/{s['lines']} บรรทัด"
        if donor
        else "ไม่มี engine ที่คืนพิกัดสำหรับหน้านี้ จึงไม่มีภาพครอปให้ดู"
    )
    st.caption(f"{note} · engine ที่ยืมมาบอกตำแหน่งอย่างเดียว ไม่มีสิทธิ์แก้ข้อความ")

    only = st.toggle("เฉพาะบรรทัดที่ต้องตรวจ", value=True, key="rv_only")
    left, right = st.columns([1, 1.15])
    with left:
        with st.container(border=True):
            if img.exists():
                uri, _w, _h = cached_image(img)
                st.markdown(
                    f'<img src="{uri}" style="width:100%;border-radius:.4rem">',
                    unsafe_allow_html=True,
                )
                st.caption(f"ภาพที่ engine อ่านจริง ({img.parent.name}/)")
            else:
                st.warning(f"ไม่พบภาพใน {img.parent.name}/")

    with right:
        for row in rows:
            if only and not row.needs_check:
                continue
            if row.needs_check:
                tags = " · ".join(dict.fromkeys(_TONE[m.kind][1] for m in row.marks))
                st.markdown(
                    f'<div class="lab">บรรทัด {row.index + 1} · {tags}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(_render(row), unsafe_allow_html=True)


def view_review(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ตรวจงาน")
    st.markdown(
        "<style>.num{background:#EEF0FF;color:#3730A3;border-radius:4px;"
        "padding:0 .12em;font-weight:600}.shaky-line{background:#FDF1DF;"
        "border-radius:4px;padding:.05em .15em}</style>",
        unsafe_allow_html=True,
    )
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    # ยุบตัวเลือกไว้ในกล่อง เลือกครั้งเดียวตอนเริ่มแล้วไม่ต้องแตะอีก
    # ของเดิมวางค้างไว้บนสุดตลอด กินที่ที่ควรเป็นของภาพครอป
    with st.expander("เลือกงานที่จะตรวจ", expanded=False):
        top = st.columns([1.8, 2.2, 1.4])
        engine = top[0].selectbox("ผลของ", sorted(results), key="rv_engine")
        ok_pages = [p for p in pages if (sp := results[engine].get(p.page_id)) and sp.ok]
        if not ok_pages:
            st.info(f"`{engine}` ยังไม่ได้อ่านหน้าไหนเลย")
            return

        docs = sorted({p.doc_name for p in ok_pages})
        doc = top[1].selectbox(
            "เอกสาร", docs, key="rv_doc", format_func=lambda d: short_doc(d, 36)
        )
        subset = [p for p in ok_pages if p.doc_name == doc]

        # ใช้ page_id เป็นค่า ไม่ใช่ PageInfo — Streamlit จำค่าที่เลือกตามคีย์
        # พอสลับ engine แล้วชุดหน้าเปลี่ยน ค่าเก่าค้างแล้วหาไม่เจอ พังทั้งแท็บ
        by_id = {p.page_id: p for p in subset}
        page_id = top[2].selectbox(
            "หน้า",
            list(by_id),
            key="rv_page",
            format_func=lambda k: f"หน้า {by_id[k].page_no}",
        )
        if page_id not in by_id:
            page_id = next(iter(by_id))
        picked = by_id[page_id]

    stored = results[engine].get(picked.page_id)
    if stored is None or not stored.ok:
        st.info(f"`{engine}` ยังไม่ได้อ่านหน้านี้ — เลือกหน้าอื่นหรือสั่งสแกนก่อน")
        return

    saved = markdown_out.load_page(picked.page_id, engine)
    lines = (
        [ln for ln in saved.splitlines() if ln.strip()]
        if saved is not None
        else stored.lines
    )
    thai_doc = thai_digit_by_document(
        {p: results[engine][p].lines for p in results[engine] if results[engine][p].ok}
    ).get(picked.page_id)

    donor = _donor_for(engine, results, picked.page_id)
    donor_page = results.get(donor, {}).get(picked.page_id) if donor else None
    rows = review.build(
        lines,
        thai_doc=thai_doc,
        shaky=_shaky_for(engine, picked.page_id),
        donor_lines=donor_page.lines if donor_page else None,
        donor_boxes=donor_page.boxes if donor_page else None,
    )
    s = review.summary(rows)

    st.caption(
        f"{short_doc(picked.doc_name, 40)} · หน้า {picked.page_no} · `{engine}` — "
        f"ต้องตรวจ {s['to_check']} จาก {s['lines']} บรรทัด"
        + (f" · ผิดแน่ {s['mixed']} จุด" if s["mixed"] else "")
    )

    img_dir = CLEAN_IMAGE_DIR if engine.endswith("+clean") else IMAGE_DIR
    img = img_dir / f"{picked.page_id}.png"

    focus, whole = st.tabs(["ตรวจทีละจุด", "ดูทั้งหน้า"])
    with focus:
        _focus_mode(picked, engine, rows, img, saved, lines)
    with whole:
        _page_mode(picked, engine, rows, img, s, donor)
