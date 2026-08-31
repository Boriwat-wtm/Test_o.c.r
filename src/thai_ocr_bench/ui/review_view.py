"""แท็บตรวจงาน — ภาพซ้ายมีกรอบชี้จุด ข้อความขวาแก้ได้ทันที

รวมสองสัญญาณที่วัดแล้วว่าคุ้มที่สุด (ดูเหตุผลเต็มใน review.py)
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
from ..config import CLEAN_IMAGE_DIR, IMAGE_DIR, RESULTS_DIR
from ..render import PageInfo
from ..suspect import thai_digit_by_document
from ..thai_text import THAI_DIGITS
from .common import cached_image, rescue_crop_uri, short_doc

# ตัวที่คืนพิกัดข้อความ เรียงตามความน่าเชื่อถือของกรอบที่วัดมา
_DONORS = ("tesseract-tha", "paddle-th", "easyocr-th")

_KIND = {
    "digit": ("num", "ตัวเลข", "#4F46E5"),
    "mixed": ("bad", "ผิดแน่", "#B0123B"),
    "shaky": ("warn", "ไม่นิ่ง", "#B45309"),
}
_ARABIC_TO_THAI = str.maketrans("0123456789", THAI_DIGITS)

CSS = """
<style>
.stu-wrap{position:relative;line-height:0}
.stu-wrap img{width:100%;border-radius:.5rem;display:block}
.stu-wrap svg{position:absolute;inset:0;width:100%;height:100%}
.stu-box{fill:none;stroke-width:6}
.stu-box.k-digit{stroke:#4F46E5}
.stu-box.k-mixed{stroke:#B0123B}
.stu-box.k-shaky{stroke:#B45309}
.stu-hit{fill:#4F46E5;opacity:.07}
.stu-hit.k-mixed{fill:#B0123B;opacity:.10}
.stu-hit.k-shaky{fill:#B45309;opacity:.10}
.stu-no{font-family:ui-monospace,monospace;font-size:34px;font-weight:700}
.num{background:#EEF0FF;color:#3730A3;border-radius:4px;padding:0 .12em;font-weight:600}
.shaky-line{background:#FDF1DF;border-radius:4px;padding:.05em .15em}
.stu-tag{display:inline-block;font-family:ui-monospace,monospace;font-size:10.5px;
  font-weight:700;padding:.1rem .45rem;border-radius:999px;margin-right:.35rem}
</style>
"""


def _donor_for(engine: str, results: dict, page_id: str) -> str | None:
    """หา engine ที่คืนพิกัด และอ่านภาพชุดเดียวกับตัวหลัก

    +clean ต้องยืมจาก +clean เท่านั้น ภาพคนละชุดพิกัดคนละที่
    """
    suffix = "+clean" if engine.endswith("+clean") else ""
    for base in _DONORS:
        page = results.get(base + suffix, {}).get(page_id)
        if page and page.ok and any(page.boxes):
            return base + suffix
    return None


def _shaky_for(engine: str, page_id: str) -> list[bool] | None:
    """ผลวัดความนิ่งของหน้านี้ ถ้าเคยรันไว้ — None แปลว่ายังไม่ได้วัด"""
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


def suggest(mark: review.Mark, text: str) -> str | None:
    """คำที่น่าจะถูก สำหรับจุดที่ตัดสินได้เอง — คืน None ถ้าเดาไม่ได้

    เดาเฉพาะกรณีที่มีคำตอบเดียวจริง ๆ คือเลขอารบิกในเอกสารเลขไทย
    ส่วนเลขที่ปนกันเองในก้อนเดียวก็แปลงเป็นไทยทั้งก้อน
    ไม่เดากรณีอื่น เพราะเดาผิดแล้วคนกดรับไปเลยจะแย่กว่าไม่เดา
    """
    if mark.kind != "mixed":
        return None
    fixed = text[mark.start : mark.end].translate(_ARABIC_TO_THAI)
    return fixed if fixed != text[mark.start : mark.end] else None


def _overlay(uri: str, w: int, h: int, rows: list) -> str:
    """วาดกรอบทับภาพตรงบรรทัดที่ต้องตรวจ พร้อมเลขกำกับให้ตรงกับฝั่งข้อความ

    ใช้ SVG ซ้อนบนภาพแทนการวาดลงไฟล์ เพราะไม่ต้องสร้างภาพใหม่ทุกครั้ง
    และกรอบยังคมชัดเมื่อผู้ใช้ซูมหน้าเว็บ

    viewBox ใช้ขนาดภาพจริง จะได้ใส่พิกัดดิบจาก engine ลงไปตรง ๆ
    ไม่ต้องแปลงสเกลเอง ซึ่งเป็นจุดที่พลาดง่ายเวลาภาพถูกย่อให้พอดีคอลัมน์
    """
    shapes = []
    n = 0
    for r in rows:
        if not r.box or not r.needs_check:
            continue
        n += 1
        x, y, bw, bh = r.box
        kind = "mixed" if any(m.kind == "mixed" for m in r.marks) else (
            "shaky" if any(m.kind == "shaky" for m in r.marks) else "digit"
        )
        colour = _KIND[kind][2]
        shapes.append(
            f'<rect class="stu-hit k-{kind}" x="{x}" y="{y}" width="{bw}" height="{bh}"/>'
            f'<rect class="stu-box k-{kind}" x="{x}" y="{y}" width="{bw}" height="{bh}"'
            f' rx="8"/>'
            f'<text class="stu-no" x="{max(x - 14, 8)}" y="{y + bh - 8}"'
            f' fill="{colour}" text-anchor="end">{r.index + 1}</text>'
        )
    return (
        f'<div class="stu-wrap"><img src="{uri}" alt="หน้าเอกสาร">'
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'{"".join(shapes)}</svg></div>'
    )


def _line_html(row: review.ReviewLine) -> str:
    """ระบายสีเฉพาะช่วงที่ต้องดู ส่วนที่เหลือปล่อยไว้

    ความไม่นิ่งครอบทั้งบรรทัด จึงวาดเป็นพื้นหลังจาง แล้ววาดตัวเลขทับ
    ไม่งั้นทั้งบรรทัดแดงจนมองไม่เห็นว่าตัวเลขอยู่ตรงไหน
    """
    spans = [m for m in row.marks if m.kind != "shaky"]
    body, cursor = [], 0
    for m in sorted(spans, key=lambda m: m.start):
        if m.start < cursor:
            continue
        body.append(html.escape(row.text[cursor : m.start]))
        cls = "wrong" if m.kind == "mixed" else "num"
        tip = m.note
        if (fix := suggest(m, row.text)):
            tip += f" · น่าจะเป็น {fix}"
        body.append(
            f'<span class="{cls}" data-tip="{html.escape(tip)}">'
            f"{html.escape(row.text[m.start : m.end])}</span>"
        )
        cursor = m.end
    body.append(html.escape(row.text[cursor:]))

    inner = "".join(body)
    if any(m.kind == "shaky" for m in row.marks):
        inner = f'<span class="shaky-line">{inner}</span>'
    return f'<div class="ln">{inner}</div>'


def _picker(pages: list[PageInfo], results: dict):
    """แถบเลือกงาน — คืน (engine, หน้า) หรือ None ถ้าเลือกไม่ได้"""
    top = st.columns([1.7, 2.1, 1.2, 1.6])
    engine = top[0].selectbox("ผลของ", sorted(results), key="rv_engine")
    ok_pages = [p for p in pages if (sp := results[engine].get(p.page_id)) and sp.ok]
    if not ok_pages:
        st.info(f"`{engine}` ยังไม่ได้อ่านหน้าไหนเลย")
        return None

    docs = sorted({p.doc_name for p in ok_pages})
    doc = top[1].selectbox(
        "เอกสาร", docs, key="rv_doc", format_func=lambda d: short_doc(d, 34)
    )
    subset = [p for p in ok_pages if p.doc_name == doc]

    # ใช้ page_id เป็นค่า ไม่ใช่ PageInfo — Streamlit จำค่าที่เลือกตามคีย์
    # พอสลับ engine แล้วชุดหน้าเปลี่ยน ค่าเก่าค้างแล้วหาไม่เจอ พังทั้งแท็บ
    by_id = {p.page_id: p for p in subset}
    page_id = top[2].selectbox(
        "หน้า", list(by_id), key="rv_page",
        format_func=lambda k: f"หน้า {by_id[k].page_no}",
    )
    if page_id not in by_id:
        page_id = next(iter(by_id))

    # ปุ่มข้ามหน้าอยู่ตรงนี้ ไม่ต้องเลื่อนกลับขึ้นมาเปลี่ยนที่ช่องเลือก
    ids = list(by_id)
    at = ids.index(page_id)
    nav = top[3].columns(2)
    if nav[0].button("‹ ก่อนหน้า", disabled=at == 0, width="stretch"):
        st.session_state["rv_page"] = ids[at - 1]
        st.rerun()
    if nav[1].button("ถัดไป ›", disabled=at >= len(ids) - 1, width="stretch"):
        st.session_state["rv_page"] = ids[at + 1]
        st.rerun()
    return engine, by_id[page_id]


def view_review(pages: list[PageInfo], results: dict) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    got = _picker(pages, results)
    if got is None:
        return
    engine, picked = got

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
    shaky = _shaky_for(engine, picked.page_id)
    rows = review.build(
        lines,
        thai_doc=thai_doc,
        shaky=shaky,
        donor_lines=donor_page.lines if donor_page else None,
        donor_boxes=donor_page.boxes if donor_page else None,
    )
    s = review.summary(rows)

    head = st.columns([3, 1.3])
    head[0].markdown(
        f'<span class="stu-tag" style="background:#EEF0FF;color:#3730A3">'
        f'ตัวเลข {s["digits"]}</span>'
        + (f'<span class="stu-tag" style="background:#FCE7EA;color:#B0123B">'
           f'ผิดแน่ {s["mixed"]}</span>' if s["mixed"] else "")
        + (f'<span class="stu-tag" style="background:#FDF1DF;color:#93630A">'
           f'ไม่นิ่ง {s["shaky"]}</span>' if shaky is not None else
           '<span class="stu-tag" style="background:#EDEFF3;color:#5B5F6B">'
           'ยังไม่ได้วัดความนิ่ง</span>'),
        unsafe_allow_html=True,
    )
    head[1].markdown(
        f'<div style="text-align:right;font-weight:700;font-size:1.05rem">'
        f'ต้องตรวจ {s["to_check"]} จาก {s["lines"]} บรรทัด</div>',
        unsafe_allow_html=True,
    )

    img_dir = CLEAN_IMAGE_DIR if engine.endswith("+clean") else IMAGE_DIR
    img = img_dir / f"{picked.page_id}.png"

    left, right = st.columns([1, 1.05])
    with left:
        st.caption(
            f"ภาพที่ engine อ่านจริง · กรอบชี้บรรทัดที่ต้องตรวจ "
            f"(ยืมพิกัดจาก `{donor}` ได้ {s['with_box']}/{s['lines']} บรรทัด)"
            if donor else "ไม่มี engine ที่คืนพิกัดสำหรับหน้านี้ จึงวาดกรอบไม่ได้"
        )
        if img.exists():
            uri, w, h = cached_image(img)
            st.markdown(_overlay(uri, w, h, rows), unsafe_allow_html=True)
        else:
            st.warning(f"ไม่พบภาพใน {img_dir.name}/")

    with right:
        editing = st.toggle("โหมดแก้ข้อความ", value=False, key="rv_edit")
        only = st.toggle("เฉพาะบรรทัดที่ต้องตรวจ", value=True, key="rv_only")
        if saved is not None:
            st.caption(f"หน้านี้มีฉบับที่แก้ไว้แล้ว {len(lines)} บรรทัด")

        edits: dict[int, str] = {}
        for row in rows:
            if only and not row.needs_check:
                continue
            if row.needs_check:
                kinds = dict.fromkeys(_KIND[m.kind][1] for m in row.marks)
                st.markdown(
                    f'<div class="lab">บรรทัด {row.index + 1} · {" · ".join(kinds)}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(_line_html(row), unsafe_allow_html=True)

            if not row.needs_check:
                continue
            hints = [f for m in row.marks if (f := suggest(m, row.text))]
            if hints:
                st.caption("น่าจะเป็น: " + " · ".join(hints))
            if editing:
                edits[row.index] = st.text_input(
                    f"บรรทัด {row.index + 1}",
                    value=row.text,
                    key=f"rv_line|{picked.page_id}|{engine}|{row.index}",
                    label_visibility="collapsed",
                )
            elif row.box:
                with st.popover("ดูภาพตรงจุดนี้", width="content"):
                    crop = rescue_crop_uri(str(img), tuple(row.box))
                    if crop:
                        st.markdown(
                            f'<img src="{crop}" style="width:100%;border-radius:.4rem;'
                            f'border:1px solid var(--border)">',
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("ยืมพิกัดบรรทัดนี้ไม่ได้ — ไม่มีภาพครอปให้ดู")

        if editing:
            _save_bar(picked.page_id, engine, lines, edits, saved is not None)


def _save_bar(
    page_id: str, engine: str, lines: list[str], edits: dict[int, str], has_saved: bool
) -> None:
    """ปุ่มบันทึก — เขียนทั้งหน้า ไม่ใช่เฉพาะบรรทัดที่แก้

    ต้องเก็บทั้งหน้าเพราะไฟล์นี้เป็นฉบับที่คนแก้แล้วของหน้านั้น แท็บ markdown
    หยิบไปใช้แทนผลดิบตอนส่งออก ถ้าเก็บแต่บรรทัดที่แก้ ที่เหลือจะหายไป
    """
    changed = {i: v for i, v in edits.items() if i < len(lines) and v != lines[i]}
    st.divider()
    cols = st.columns([1.6, 1.3, 2])
    if cols[0].button(
        f"ยืนยันการแก้ไข ({len(changed)})" if changed else "ยืนยันการแก้ไข",
        type="primary",
        disabled=not changed,
        key=f"rv_save|{page_id}",
    ):
        merged = [edits.get(i, ln) for i, ln in enumerate(lines)]
        markdown_out.save_page(page_id, engine, "\n".join(merged))
        st.success(f"บันทึกแล้ว {len(changed)} บรรทัด")
        st.rerun()

    if has_saved and cols[1].button("ล้างที่แก้ไว้", key=f"rv_reset|{page_id}"):
        markdown_out.clear_page(page_id, engine)
        st.rerun()

    cols[2].caption(
        "บันทึกแล้วแท็บ markdown จะใช้ฉบับนี้แทนผลดิบตอนส่งออก "
        "· ผลดิบเดิมไม่ถูกแก้ ย้อนกลับได้เสมอ"
    )
