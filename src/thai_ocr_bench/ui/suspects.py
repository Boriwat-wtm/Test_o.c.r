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
    thai_digit_by_document,
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

    lines_of = {pid: lines for pid, (lines, _b) in per_engine[engine].items()}

    # ทั้งสองกฎนี้ตัดสินที่ระดับเอกสาร ไม่ใช่ระดับหน้าและไม่ใช่ระดับทั้งคลัง
    #   thai_digit_by_document  เอกสารนี้ใช้เลขไทยหรือเลขอารบิก
    #   section_findings_...    ฐานนิยมความยาวเลขมาตราของเอกสารนี้
    thai_doc_of = thai_digit_by_document(lines_of)

    by_doc: dict[str, dict[str, list[str]]] = {}
    for pid, lines in lines_of.items():
        by_doc.setdefault(pid.rsplit("_p", 1)[0], {})[pid] = lines
    section_findings: dict[str, dict[int, list]] = {}
    for doc_pages in by_doc.values():
        section_findings.update(section_findings_by_document(doc_pages))

    out = []
    for pid in sorted(per_engine[engine]):
        page = {n: v[pid] for n, v in per_engine.items() if pid in v}
        out.extend(scan_page(pid, engine, page, thai_doc=thai_doc_of[pid]))
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


def _summary_bar(engine: str, suspects: list, results: dict) -> None:
    """แถวตัวเลขบนสุด — บอกว่าต้องตรวจเยอะแค่ไหนก่อนจะเริ่มไล่ดู"""
    total_lines = sum(len(p.lines) for p in results[engine].values())
    rule = sum(1 for s in suspects if "rule" in s.layers)
    vote = sum(1 for s in suspects if "vote" in s.layers)

    a, b, c, d = st.columns(4)
    a.metric("บรรทัดทั้งหมด", f"{total_lines:,}")
    b.metric(
        "จุดน่าสงสัย",
        len(suspects),
        f"{len(suspects) / total_lines:.1%} ของทั้งหมด" if total_lines else None,
        delta_color="off",
    )
    c.metric("จากกฎตายตัว", rule, "ตัดสินได้เอง", delta_color="off")
    d.metric("จาก engine อื่น", vote, "ต้องดูภาพ", delta_color="off")


def view_suspects(pages: list[PageInfo], results: dict) -> None:
    st.subheader("จุดน่าสงสัย")
    st.caption(
        "หาจุดที่น่าจะอ่านผิดโดยไม่ใช้เฉลย จึงใช้กับเอกสารที่ยังไม่มีใครทำเฉลยได้ "
        "— ซึ่งเป็นกรณีของงานจริง"
    )
    if not results:
        st.warning("ยังไม่มีผล OCR")
        return

    top = st.columns([2.2, 1.4, 1.4])
    engine = top[0].selectbox("ตรวจ engine", sorted(results))
    only = top[1].selectbox(
        "กรองชั้น",
        ["ทั้งหมด", "กฎตายตัว", "engine อื่นไม่เห็นด้วย"],
        help="กฎตายตัว = ตัดสินได้โดยไม่ต้องดูภาพ · "
        "engine อื่นไม่เห็นด้วย = ต้องเปิดภาพดูเอง",
    )
    per_page = top[2].number_input(
        "แสดงกี่จุดต่อครั้ง", min_value=10, max_value=500, value=25, step=25,
        help="ของเดิมกางทุกจุดพร้อมภาพครอปทั้งหมด หน้าจึงยาวจนเลื่อนหาไม่เจอ",
    )

    suspects = _scan_suspects(engine, results)
    want = {"กฎตายตัว": "rule", "engine อื่นไม่เห็นด้วย": "vote"}.get(only)
    if want:
        suspects = [s for s in suspects if want in s.layers]

    _summary_bar(engine, suspects, results)

    voters = independent_peers(engine, list(results))
    st.caption(
        "ผู้โหวต: " + (" · ".join(voters) if voters else "ไม่มี — เหลือแต่ชั้นกฎตายตัว")
    )

    if not suspects:
        st.success("ไม่พบจุดน่าสงสัย — ไม่ได้แปลว่าไม่มีที่ผิด แปลว่าสองชั้นนี้จับไม่ได้")
        return

    # จัดกลุ่มตามหน้า เพราะคนตรวจทำงานทีละหน้า ไม่ได้กระโดดข้ามหน้าไปมา
    # ของเดิมเรียงเป็นรายการยาวเส้นเดียว ต้องเลื่อนหาว่าจุดไหนอยู่หน้าไหนเอง
    by_page: dict[str, list] = {}
    for s in suspects:
        by_page.setdefault(s.page_id, []).append(s)

    shown = 0
    img_dir = image_dir_for(engine)
    st.divider()

    for page_id, items in by_page.items():
        if shown >= per_page:
            break
        with st.expander(f"**{page_id}** · {len(items)} จุด", expanded=shown == 0):
            for s in items:
                if shown >= per_page:
                    st.caption("— เหลืออีกในหน้านี้ เพิ่มจำนวนที่แสดงด้านบน —")
                    break
                shown += 1

                tags = " ".join(
                    pill(
                        "กฎตายตัว" if lay == "rule" else "engine อื่นไม่เห็นด้วย",
                        "warn" if lay == "rule" else "bad",
                    )
                    for lay in sorted(s.layers)
                )
                st.markdown(
                    f'<div class="lab">บรรทัดที่ {s.grid_line + 1}</div>{tags}',
                    unsafe_allow_html=True,
                )
                st.markdown(highlight(s.text, s.findings), unsafe_allow_html=True)

                for f in s.findings:
                    st.caption(f"「{f.text}」 → น่าจะเป็น 「{f.suggestion}」 · {f.reason}")

                # ภาพครอปซ่อนไว้ใต้ปุ่มกาง ไม่กางเอง — ของเดิมโหลดภาพทุกจุด
                # พร้อมกันทำให้หน้าอืดและยาวมากเมื่อมีหลายสิบจุด
                if s.box:
                    with st.popover("ดูภาพครอป", width="content"):
                        uri = _crop(str(img_dir / f"{s.page_id}.png"), s.box)
                        if uri:
                            st.markdown(
                                f'<img src="{uri}" style="width:100%;border-radius:.5rem;'
                                f'border:1px solid var(--border)">',
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                "ครอปจากภาพต้นฉบับตามขนาดจริง (ไม่ได้ขยาย) · พิกัด"
                                f"{' ' + s.box_from if s.box_from else ''}"
                            )
                else:
                    st.caption("ไม่มีภาพครอป — จุดนี้มาจากกฎที่ดูทั้งเอกสาร ไม่ผูกกับพิกัด")
                st.markdown("---")

    st.caption(f"แสดง {shown} จาก {len(suspects)} จุด")
