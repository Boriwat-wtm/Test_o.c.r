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
from .common import cached_image, peek_uri, short_doc

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
.stu-doc{border:1px solid var(--border,#E4E6EC);border-radius:.6rem;
  padding:1rem 1.15rem;background:var(--paper,#fff);max-height:62vh;overflow-y:auto}
.stu-row{display:flex;gap:.7rem;align-items:baseline;padding:.12rem 0}
.stu-row.hit{background:rgba(79,70,229,.045);border-radius:.3rem;
  margin:0 -.35rem;padding:.12rem .35rem}
.stu-gut{font-family:ui-monospace,monospace;font-size:11px;color:#8C919E;
  min-width:2.2em;text-align:right;flex:none;user-select:none}
.stu-txt{font-size:15.5px;line-height:1.95;word-break:break-word;flex:1}

/* ภาพครอปเด้งตอนชี้เมาส์ที่ช่วงที่ mark — เร็วกว่าเลือกบรรทัดจาก dropdown
   ใช้ CSS ล้วน ไม่ง้อ JS เพราะ Streamlit ตัด script ที่ฝังมากับ markdown ทิ้ง */
.stu-peek{position:relative}
.stu-peek>.pk{display:none;position:absolute;left:0;bottom:calc(100% + 10px);
  z-index:60;padding:.35rem;background:#fff;border:1px solid #CFD3DD;
  border-radius:.5rem;box-shadow:0 8px 26px rgba(20,22,27,.16);
  width:min(560px,78vw)}
.stu-peek>.pk img{display:block;width:100%;border-radius:.3rem}
.stu-peek>.pk .cap{font-size:11px;color:#5B5F6B;padding:.25rem .1rem 0}
.stu-peek:hover>.pk{display:block}
.stu-doc{overflow:visible}
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


def _inline(row: review.ReviewLine, peek: str | None = None) -> str:
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
        chunk = (
            f'<span class="{cls}" data-tip="{html.escape(tip)}">'
            f"{html.escape(row.text[m.start : m.end])}</span>"
        )
        if peek:
            # ห่อทีละช่วง ไม่ใช่ทั้งบรรทัด — ชี้ตรงตัวเลขแล้วเด้ง ไม่ใช่ชี้ตรงไหน
            # ในบรรทัดก็เด้ง ซึ่งจะบังข้อความรอบ ๆ ตลอดเวลาที่เลื่อนเมาส์ผ่าน
            chunk = (
                f'<span class="stu-peek">{chunk}'
                f'<span class="pk"><img src="{peek}" alt="ภาพบรรทัดนี้">'
                f'<span class="cap">บรรทัด {row.index + 1} จากภาพจริง</span></span></span>'
            )
        body.append(chunk)
        cursor = m.end
    body.append(html.escape(row.text[cursor:]))

    inner = "".join(body)
    if any(m.kind == "shaky" for m in row.marks):
        inner = f'<span class="shaky-line">{inner}</span>'
    return inner


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
    # ช่องนี้ก็จำค่าเก่าเหมือนช่องหน้า สลับ engine แล้วเอกสารที่เลือกไว้อาจไม่มี
    # ใน engine ใหม่ ทำให้ subset ว่าง แล้ว next(iter(by_id)) โยน StopIteration
    if doc not in docs:
        doc = docs[0]
    subset = [p for p in ok_pages if p.doc_name == doc]
    if not subset:
        st.info(f"`{engine}` ยังไม่ได้อ่านเอกสารนี้ — เลือกเอกสารอื่นหรือสั่งสแกนก่อน")
        return None

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
        _text_panel(picked, engine, rows, lines, saved, img, s)


def _text_panel(picked, engine, rows, lines, saved, img, s) -> None:
    """ฝั่งข้อความ — แสดงเป็นเอกสารต่อเนื่อง ไม่ใช่บรรทัดละก้อน

    ของเดิมวาดป้าย "บรรทัด N · ตัวเลข" กับคำอธิบายคั่นทุกบรรทัดที่ mark
    ผลคือข้อความถูกหั่นเป็นชิ้น อ่านเป็นเอกสารไม่ได้ ทั้งที่คนตรวจต้อง
    อ่านความต่อเนื่องเพื่อรู้ว่าคำไหนควรเป็นอะไร

    ตอนนี้เลขบรรทัดอยู่ริมซ้ายเป็นแถบ gutter บรรทัดที่ต้อง mark มีพื้นหลังจาง
    ข้อมูลว่าทำไมถึง mark ย้ายไปอยู่ใน tooltip ของช่วงที่ระบายสี
    """
    bar = st.columns([1.3, 1.4, 1.6])
    editing = bar[0].toggle("แก้ข้อความ", value=False, key="rv_edit")
    only = bar[1].toggle("เฉพาะที่ต้องตรวจ", value=True, key="rv_only")
    if saved is not None:
        bar[2].caption(f"มีฉบับที่แก้ไว้ {len(lines)} บรรทัด")

    if editing:
        _edit_panel(picked, engine, lines, saved)
        return

    shown = [r for r in rows if r.needs_check or not only]
    if not shown:
        st.success("ไม่มีบรรทัดไหนต้องตรวจ — ไม่ได้แปลว่าอ่านถูกหมด")
        return

    mtime = img.stat().st_mtime if img.exists() else 0.0
    body = []
    for r in shown:
        cls = "stu-row hit" if r.needs_check else "stu-row"
        peek = (
            peek_uri(str(img), tuple(r.box), mtime)
            if r.needs_check and r.box and img.exists()
            else None
        )
        body.append(
            f'<div class="{cls}"><span class="stu-gut">{r.index + 1}</span>'
            f'<span class="stu-txt">{_inline(r, peek)}</span></div>'
        )
    st.markdown(f'<div class="stu-doc">{"".join(body)}</div>', unsafe_allow_html=True)
    st.caption("ชี้เมาส์ที่ช่วงที่ระบายสีเพื่อดูภาพจริงตรงจุดนั้น")

    # คำแนะนำรวมไว้ที่เดียวใต้กล่อง ไม่แทรกคั่นกลางข้อความ
    hints = [
        f"บรรทัด {r.index + 1}: {f}"
        for r in shown
        for m in r.marks
        if (f := suggest(m, r.text))
    ]
    if hints:
        st.caption("แก้ได้เลยโดยไม่ต้องดูภาพ — " + " · ".join(hints[:6]))

    if s["with_box"] < s["lines"]:
        st.caption(
            f"ยืมพิกัดได้ {s['with_box']}/{s['lines']} บรรทัด — "
            "ที่เหลือกดดูภาพตรงจุดไม่ได้ ต้องสแกน tesseract หน้านี้เพิ่ม"
        )


def _edit_panel(picked, engine, lines: list[str], saved: str | None) -> None:
    """แก้ทั้งหน้าในช่องเดียว ไม่ใช่ช่องละบรรทัด

    ช่องละบรรทัดทำให้ย้ายข้อความข้ามบรรทัดไม่ได้ ซึ่งจำเป็นเวลา OCR
    หั่นบรรทัดผิดที่ — เคสที่เจอบ่อยกับ engine ที่ตีกรอบพลาด
    """
    text = st.text_area(
        "ข้อความทั้งหน้า",
        value="\n".join(lines),
        height=460,
        key=f"rv_area|{picked.page_id}|{engine}",
        label_visibility="collapsed",
    )
    new = [ln.strip() for ln in text.splitlines() if ln.strip()]
    changed = new != lines

    b = st.columns([1.5, 1.3, 2])
    if b[0].button(
        "บันทึกการแก้ไข", type="primary", disabled=not changed,
        key=f"rv_save|{picked.page_id}",
    ):
        markdown_out.save_page(picked.page_id, engine, "\n".join(new))
        st.success(f"บันทึกแล้ว {len(new)} บรรทัด")
        st.rerun()

    if saved is not None and b[1].button("ล้างที่แก้ไว้", key=f"rv_reset|{picked.page_id}"):
        markdown_out.clear_page(picked.page_id, engine)
        st.rerun()

    b[2].caption(
        f"{len(new)} บรรทัด · "
        + ("มีการแก้ ยังไม่บันทึก" if changed else "ยังไม่ได้แก้อะไร")
    )
