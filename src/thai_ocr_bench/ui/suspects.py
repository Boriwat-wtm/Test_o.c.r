"""แท็บจุดน่าสงสัย — หาจุดที่น่าจะอ่านผิดโดยไม่ใช้เฉลย"""

from __future__ import annotations

import html

import streamlit as st

from ..render import PageInfo
from ..suspect import (
    independent_peers,
    scan_page,
    section_findings_by_document,
    section_suspects,
    thai_digit_document,
)
from .common import _crop, image_dir_for
from .theme import pill

@st.cache_data(show_spinner="กำลังหาจุดน่าสงสัย…")
def _scan_suspects(engine: str, _results: dict) -> list:
    """ไล่ทุกหน้าหาจุดน่าสงสัยของ engine หนึ่งตัว

    ไม่ใช้เฉลยเลย จึงใช้กับเอกสารที่ยังไม่มีคนทำเฉลยได้ ซึ่งเป็นกรณีของงานจริง
    """
    per_engine = {
        name: {
            pid: (page.lines, [b if b else None for b in page.boxes])
            for pid, page in pages.items()
        }
        for name, pages in _results.items()
    }
    if engine not in per_engine:
        return []

    # เหลือเฉพาะตัวที่ให้ความเห็นอิสระ + ตัวเป้าหมายเอง
    keep = set(independent_peers(engine, list(per_engine))) | {engine}
    per_engine = {n: v for n, v in per_engine.items() if n in keep}

    thai_doc = thai_digit_document(
        [ln for lines, _ in per_engine[engine].values() for ln in lines]
    )

    # เลขมาตรายาวผิดปกติต้องตั้งฐานนิยมจากทั้งเอกสาร ไม่ใช่ทีละหน้า (หน้าเดียว
    # มักมีเลขมาตราน้อยเกินจะตั้งฐานนิยมได้แม่น — ดู section_findings_by_document)
    by_doc: dict[str, dict[str, list[str]]] = {}
    for pid, (lines, _boxes) in per_engine[engine].items():
        by_doc.setdefault(pid.rsplit("_p", 1)[0], {})[pid] = lines
    section_findings: dict[str, dict[int, list]] = {}
    for doc_pages in by_doc.values():
        section_findings.update(section_findings_by_document(doc_pages))

    out = []
    for pid in sorted(per_engine[engine]):
        page = {n: v[pid] for n, v in per_engine.items() if pid in v}
        out.extend(scan_page(pid, engine, page, thai_doc=thai_doc))
        lines = per_engine[engine][pid][0]
        out.extend(section_suspects(pid, engine, lines, section_findings.get(pid, {})))
    return out


def highlight(text: str, findings: list) -> str:
    """ระบายสีเฉพาะช่วงที่น่าสงสัย ส่วนที่เหลือปล่อยไว้"""
    marks = []
    cursor = 0
    for f in sorted(findings, key=lambda f: f.start):
        if f.start < cursor:
            continue
        marks.append(html.escape(text[cursor:f.start]))
        tip = f"{html.escape(f.reason)} — น่าจะเป็น: {html.escape(f.suggestion)}"
        marks.append(f'<span class="wrong" data-tip="{tip}">{html.escape(f.text) or "␣"}</span>')
        cursor = f.end
    marks.append(html.escape(text[cursor:]))
    return f'<div class="ln">{"".join(marks)}</div>'


def view_suspects(pages: list[PageInfo], results: dict) -> None:
    st.subheader("จุดน่าสงสัย")
    st.caption(
        "หาจุดที่น่าจะอ่านผิดโดยไม่ใช้เฉลย — ใช้ได้กับเอกสารที่ยังไม่มีใครทำเฉลย "
        "กฎตายตัว (เลขยกกำลัง เลขอารบิกปนในเอกสารเลขไทย เลขมาตรายาวผิดปกติเทียบ"
        "กับทั้งเอกสาร — จุดหลังไม่มีภาพครอปให้เพราะไม่ผ่านกริดตำแหน่ง) "
        "และการที่ engine อื่นตั้งแต่สองตัวขึ้นไปอ่านได้ไม่ตรงกับตัวนี้"
    )
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    top = st.columns([2, 1, 1])
    engine = top[0].selectbox("ตรวจ engine", sorted(results))
    only = top[1].selectbox("กรองชั้น", ["ทั้งหมด", "กฎตายตัว", "engine อื่นไม่เห็นด้วย"])
    show_crop = top[2].toggle("แสดงภาพครอป", value=True)

    suspects = _scan_suspects(engine, results)
    want = {"กฎตายตัว": "rule", "engine อื่นไม่เห็นด้วย": "vote"}.get(only)
    if want:
        suspects = [s for s in suspects if want in s.layers]

    voters = independent_peers(engine, list(results))
    st.caption(
        "ผู้โหวต: " + (" · ".join(voters) if voters else "ไม่มี — เหลือแต่ชั้นกฎตายตัว")
    )

    total_lines = sum(len(p.lines) for p in results[engine].values())
    a, b, c = st.columns(3)
    a.metric("บรรทัดทั้งหมด", total_lines)
    b.metric("จุดน่าสงสัย", len(suspects))
    c.metric("สัดส่วนที่ต้องตรวจ", f"{len(suspects) / total_lines:.1%}" if total_lines else "-")

    if not suspects:
        st.success("ไม่พบจุดน่าสงสัย — ไม่ได้แปลว่าไม่มีที่ผิด แปลว่าสองชั้นนี้จับไม่ได้")
        return

    st.divider()
    img_dir = image_dir_for(engine)
    for s in suspects:
        with st.container(border=True):
            head = st.columns([3, 2])
            head[0].markdown(f"**{s.page_id}** · บรรทัดที่ {s.grid_line + 1}")
            tags = " ".join(
                pill("กฎตายตัว" if lay == "rule" else "engine อื่นไม่เห็นด้วย",
                     "warn" if lay == "rule" else "bad")
                for lay in sorted(s.layers)
            )
            head[1].markdown(tags, unsafe_allow_html=True)

            if show_crop and s.box:
                uri = _crop(str(img_dir / f"{s.page_id}.png"), s.box)
                if uri:
                    st.markdown(
                        f'<img src="{uri}" style="width:100%;border-radius:.5rem;'
                        f'border:1px solid var(--border)">',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"ครอปจากภาพจริง · พิกัด{' ' + s.box_from if s.box_from else ''}")

            st.markdown(highlight(s.text, s.findings), unsafe_allow_html=True)
            for f in s.findings:
                st.caption(f"「{f.text}」 → น่าจะเป็น 「{f.suggestion}」 · {f.reason}")


