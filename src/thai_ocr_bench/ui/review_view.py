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

from .. import review
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


def view_review(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ตรวจงาน")
    st.caption(
        "ชี้เฉพาะจุดที่ควรดู แล้วเปิดภาพตรงจุดนั้นให้ — "
        "ตัวเลขกินพื้นที่ 2.8% ของหน้าแต่ครอบคลุมความผิด 45%"
    )
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    st.markdown(
        "<style>.num{background:#EEF0FF;color:#3730A3;border-radius:4px;padding:0 .12em;"
        "font-weight:600}.shaky-line{background:#FDF1DF;border-radius:4px;"
        "padding:.05em .15em}</style>",
        unsafe_allow_html=True,
    )

    top = st.columns([1.8, 2.2, 1.6])
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
    picked = top[2].selectbox(
        "หน้า", subset, key="rv_page", format_func=lambda p: f"หน้า {p.page_no}"
    )

    lines = results[engine][picked.page_id].lines
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

    c = st.columns(4)
    c[0].metric("บรรทัดทั้งหมด", s["lines"])
    c[1].metric("ต้องตรวจ", s["to_check"], f"ข้ามได้ {s['lines'] - s['to_check']}",
                delta_color="off")
    c[2].metric("ตัวเลข", s["digits"] + s["mixed"],
                f"ผิดแน่ {s['mixed']}" if s["mixed"] else "เทียบกับภาพ", delta_color="off")
    c[3].metric("ไม่นิ่ง", s["shaky"],
                "จากการอ่านซ้ำ" if s["shaky"] else "ยังไม่ได้วัด", delta_color="off")

    note = f"ยืมพิกัดจาก `{donor}` — ได้ {s['with_box']}/{s['lines']} บรรทัด" if donor \
        else "ไม่มี engine ที่คืนพิกัดสำหรับหน้านี้ จึงกดดูภาพตรงจุดไม่ได้"
    st.caption(
        f"{note} · engine ที่ยืมมามีหน้าที่บอกตำแหน่งอย่างเดียว ไม่มีสิทธิ์แก้ข้อความ"
    )
    st.divider()

    only = st.toggle("แสดงเฉพาะบรรทัดที่ต้องตรวจ", value=True, key="rv_only")
    left, right = st.columns([1, 1.15])

    img_dir = CLEAN_IMAGE_DIR if engine.endswith("+clean") else IMAGE_DIR
    img = img_dir / f"{picked.page_id}.png"
    with left:
        with st.container(border=True):
            if img.exists():
                uri, w, h = cached_image(img)
                st.markdown(
                    f'<img src="{uri}" style="width:100%;border-radius:.4rem">',
                    unsafe_allow_html=True,
                )
                st.caption(f"ภาพที่ engine อ่านจริง ({img_dir.name}/)")
            else:
                st.warning(f"ไม่พบภาพใน {img_dir.name}/")

    with right:
        shown = 0
        for row in rows:
            if only and not row.needs_check:
                continue
            shown += 1
            if row.needs_check:
                tags = " · ".join(
                    dict.fromkeys(_TONE[m.kind][1] for m in row.marks)
                )
                st.markdown(
                    f'<div class="lab">บรรทัด {row.index + 1} · {tags}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(_render(row), unsafe_allow_html=True)
            if row.needs_check and row.box:
                with st.popover("ดูภาพตรงจุดนี้", width="content"):
                    uri = rescue_crop_uri(str(img), tuple(row.box))
                    if uri:
                        st.markdown(
                            f'<img src="{uri}" style="width:100%;border-radius:.4rem;'
                            f'border:1px solid var(--border)">',
                            unsafe_allow_html=True,
                        )
                        st.caption("ครอปบรรทัดนี้แล้วขยาย")
            elif row.needs_check:
                st.caption("ยืมพิกัดบรรทัดนี้ไม่ได้ — จับคู่กับ engine ที่คืนพิกัดไม่ติด")
        if not shown:
            st.success("ไม่มีบรรทัดไหนเข้าเงื่อนไข — ไม่ได้แปลว่าอ่านถูกหมด")
