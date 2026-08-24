"""แท็บสรุปผล — ตารางคะแนนรวมของทุก engine เทียบกัน"""

from __future__ import annotations

import streamlit as st

from .. import store
from ..metrics import align_lines, page_cer, thai_digit_report
from ..render import PageInfo
from ..truth import load as load_truth

@st.cache_data(show_spinner=False, max_entries=4096)
def scored_page(truth_lines: list[str], pred_lines: tuple[str, ...]) -> dict:
    """คะแนนของหนึ่ง (หน้า, engine) — แคชไว้เพราะแท็บสรุปผลคำนวณใหม่ทุก rerun

    st.tabs() รันเนื้อหาทุกแท็บทุกรอบ แค่ซ่อนด้วย CSS แท็บสรุปผลจึงจับคู่
    ทุก engine กับทุกหน้าที่มีเฉลยใหม่ทั้งหมด แม้ผู้ใช้จะอยู่แท็บอื่น
    วัดแล้ว 215 คู่ใช้ 3.7 วินาที ทุกครั้งที่กดอะไรก็ตาม และโตตามผลที่สะสม

    ผลของ (เฉลย, ข้อความที่อ่านได้) คู่หนึ่งไม่มีวันเปลี่ยน จึงแคชได้ปลอดภัย
    รับ pred_lines เป็น tuple เพื่อให้ hash ได้
    """
    lines = list(pred_lines)
    score = align_lines(truth_lines, lines)
    report = thai_digit_report("\n".join(truth_lines), "\n".join(lines))
    n = int(report["total"] or 0)
    return {
        "edits": sum(s.edits for s in score.matched),
        "chars": sum(s.truth_len for s in score.matched),
        "missed": score.missed_lines,
        "found": score.truth_lines - score.missed_lines,
        "spurious": score.spurious_lines,
        "page_cer": page_cer(truth_lines, lines),
        "d_total": n,
        "d_strict": round(float(report["strict"] or 0) * n),
        "d_lenient": round(float(report["lenient"] or 0) * n),
    }


def view_summary(pages: list[PageInfo], results: dict) -> None:
    st.subheader("สรุปผลรวม")

    truth = load_truth()
    scope = [p for p in pages if p.page_id in truth]
    if not scope:
        st.warning("ยังไม่มีเฉลย")
        return

    by_doc = st.checkbox("แยกตามเอกสาร", value=True)
    rows = []

    for name, per_page in sorted(results.items()):
        groups: dict[str, list[PageInfo]] = {}
        for page in scope:
            key = page.doc_name if by_doc else "ทั้งหมด"
            groups.setdefault(key, []).append(page)

        for group, group_pages in groups.items():
            edits = chars = missed = found = spurious = 0
            d_total = d_strict = d_lenient = 0
            times: list[float] = []

            page_cers: list[float] = []
            for page in group_pages:
                stored = per_page.get(page.page_id)
                if stored is None or not stored.ok:
                    continue
                sc = scored_page(truth[page.page_id].lines, tuple(stored.lines))
                if sc["page_cer"] is not None:
                    page_cers.append(sc["page_cer"])
                edits += sc["edits"]
                chars += sc["chars"]
                missed += sc["missed"]
                found += sc["found"]
                spurious += sc["spurious"]
                times.append(stored.core_ms / 1000)

                if sc["d_total"]:
                    d_total += sc["d_total"]
                    d_strict += sc["d_strict"]
                    d_lenient += sc["d_lenient"]

            if not chars:
                continue
            rows.append(
                {
                    "engine": name,
                    "ขอบเขต": group,
                    "CER บรรทัด": f"{edits / chars:.1%}",
                    "CER หน้า": f"{sum(page_cers) / len(page_cers):.1%}" if page_cers else "-",
                    "อ่านครบ": f"{found}/{found + missed}",
                    "บรรทัดเกิน": spurious,
                    "เลขไทย strict": f"{d_strict / d_total:.0%}" if d_total else "-",
                    "เลขไทย lenient": f"{d_lenient / d_total:.0%}" if d_total else "-",
                    "วิ/หน้า": f"{sum(times) / len(times):.1f}" if times else "-",
                }
            )

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("ยังไม่มีผลที่จับคู่กับเฉลยได้")

    meta = store.load_meta()
    if meta.get("versions"):
        with st.expander("เวอร์ชันที่ใช้รัน"):
            st.json({k: v for k, v in meta["versions"].items() if v})


