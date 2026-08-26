"""แท็บสรุปผล — ตารางคะแนนรวมของทุก engine เทียบกัน

ของเดิมยัดตัวเลขเป็นสตริงจัดรูปแล้ว ("5.8%") ลงตาราง ทำให้เรียงลำดับไม่ได้
เพราะ Streamlit เรียงตามตัวอักษร "10.0%" จึงมาก่อน "5.8%" ซึ่งกลับหัวกับความจริง
ไฟล์นี้เก็บค่าเป็นตัวเลขจริงแล้วให้ column_config จัดรูปตอนแสดงแทน
"""

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


def _rows(scope: list[PageInfo], results: dict, truth: dict, by_doc: bool) -> list[dict]:
    """รวมคะแนนรายหน้าเป็นแถวเดียวต่อ (engine × ขอบเขต)

    เก็บเป็นตัวเลขดิบ ไม่จัดรูปเป็นสตริงตรงนี้ เพราะตารางต้องเรียงลำดับได้
    และคอลัมน์แบบแถบ (ProgressColumn) ต้องการค่าเป็นตัวเลขเท่านั้น
    """
    out: list[dict] = []
    for name, per_page in sorted(results.items()):
        groups: dict[str, list[PageInfo]] = {}
        for page in scope:
            groups.setdefault(page.doc_name if by_doc else "ทั้งหมด", []).append(page)

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
            out.append(
                {
                    "engine": name,
                    "ขอบเขต": group,
                    "หน้า": len(times),
                    "CER บรรทัด": edits / chars,
                    "CER หน้า": sum(page_cers) / len(page_cers) if page_cers else None,
                    "อ่านครบ": found / (found + missed) if (found + missed) else None,
                    "บรรทัดเกิน": spurious,
                    "เลขไทย strict": d_strict / d_total if d_total else None,
                    "เลขไทย lenient": d_lenient / d_total if d_total else None,
                    "วิ/หน้า": sum(times) / len(times) if times else None,
                }
            )
    return out


def _leaders(rows: list[dict]) -> None:
    """แถวการ์ดบนสุด — ตอบคำถามแรกที่ทุกคนถามคือ "ตัวไหนดีที่สุด"

    ตารางล้วน ๆ ตอบคำถามนี้ไม่ได้ ต้องกวาดตาเทียบเองทีละคอลัมน์
    เลือกจากขอบเขต "ทั้งหมด" ถ้ามี ไม่งั้นเฉลี่ยข้ามเอกสารจะเอนไปตาม
    เอกสารที่มีหน้าเยอะกว่า ซึ่งไม่ใช่คำตอบที่ถูกของคำถามนี้
    """
    pool = [r for r in rows if r["ขอบเขต"] == "ทั้งหมด"] or rows
    if not pool:
        return

    picks = [
        ("แม่นที่สุด", "CER บรรทัด", "{:.2%}", True),
        ("อ่านครบที่สุด", "อ่านครบ", "{:.1%}", False),
        ("เลขไทยดีที่สุด", "เลขไทย strict", "{:.0%}", False),
        ("เร็วที่สุด", "วิ/หน้า", "{:.1f} วิ", True),
    ]
    cols = st.columns(len(picks))
    for col, (label, key, fmt, lower_better) in zip(cols, picks):
        valid = [r for r in pool if r.get(key) is not None]
        if not valid:
            col.metric(label, "-")
            continue
        best = (min if lower_better else max)(valid, key=lambda r: r[key])
        col.metric(label, best["engine"], fmt.format(best[key]), delta_color="off")


def view_summary(pages: list[PageInfo], results: dict) -> None:
    st.subheader("สรุปผลรวม")
    st.caption(
        "นับเฉพาะหน้าที่มีเฉลยเท่านั้น · CER ต่ำกว่าดีกว่า · "
        "กดหัวคอลัมน์เพื่อเรียงลำดับได้"
    )

    truth = load_truth()
    scope = [p for p in pages if p.page_id in truth]
    if not scope:
        st.warning("ยังไม่มีเฉลย — ไปที่แท็บ ✏️ ทำเฉลย ก่อน")
        return

    by_doc = st.toggle(
        "แยกตามเอกสาร",
        value=False,
        help="ปิดไว้ = รวมทุกเอกสารเป็นแถวเดียวต่อ engine ซึ่งเทียบกันง่ายกว่า",
    )
    rows = _rows(scope, results, truth, by_doc)
    if not rows:
        st.info("ยังไม่มีผลที่จับคู่กับเฉลยได้")
        return

    if not by_doc:
        _leaders(rows)
        st.divider()

    # เรียงตามความแม่นให้เลย ไม่ต้องให้ผู้ใช้กดเอง — เป็นลำดับที่คนอยากเห็นก่อนเสมอ
    rows.sort(key=lambda r: (r["ขอบเขต"], r["CER บรรทัด"]))

    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        column_config={
            "engine": st.column_config.TextColumn("engine", width="medium"),
            "ขอบเขต": st.column_config.TextColumn("ขอบเขต", width="medium"),
            "หน้า": st.column_config.NumberColumn("หน้า", width="small"),
            # ต้องใช้ format="percent" ไม่ใช่ printf "%.2f%%"
            # printf ใส่รูปให้ค่าดิบตรง ๆ ไม่คูณ 100 ให้ ค่า 0.058 จะออกมาเป็น
            # "0.06%" แทนที่จะเป็น "5.80%" ส่วน "percent" คูณให้เอง
            #
            # CER ไม่ใช้แถบ (ProgressColumn) เพราะค่าดี ๆ อยู่แถว 0-6%
            # แถบที่สเกล 0-100% จะสั้นเท่ากันหมดจนแยกตัวที่ดีกว่ากันไม่ออก
            "CER บรรทัด": st.column_config.NumberColumn("CER บรรทัด", format="percent"),
            "CER หน้า": st.column_config.NumberColumn("CER หน้า", format="percent"),
            "อ่านครบ": st.column_config.ProgressColumn(
                "อ่านครบ", format="percent", min_value=0, max_value=1
            ),
            "บรรทัดเกิน": st.column_config.NumberColumn("บรรทัดเกิน", width="small"),
            "เลขไทย strict": st.column_config.ProgressColumn(
                "เลขไทย strict", format="percent", min_value=0, max_value=1,
                help="ต้องได้เลขไทยตรงตัว — เป็นสิ่งที่งานนี้วัดโดยตรง",
            ),
            "เลขไทย lenient": st.column_config.ProgressColumn(
                "เลขไทย lenient", format="percent", min_value=0, max_value=1,
                help="แปลงเป็นเลขอารบิกทั้งสองฝั่งก่อนเทียบ — ช่องว่างจาก strict "
                "บอกว่าความผิดกู้คืนได้หรือไม่",
            ),
            "วิ/หน้า": st.column_config.NumberColumn("วิ/หน้า", format="%.1f"),
        },
    )

    with st.expander("อ่านตัวเลขพวกนี้ยังไง"):
        st.markdown(
            "- **CER บรรทัด** — นับเฉพาะบรรทัดที่จับคู่กับเฉลยได้ ตอบว่า"
            " *อ่านตัวอักษรแม่นแค่ไหน*\n"
            "- **CER หน้า** — ต่อทั้งหน้าเป็นก้อนเดียวแล้วเทียบ ตอบว่า"
            " *ผลรวมทั้งหน้าใช้ได้แค่ไหน* — ตัวที่รวมย่อหน้า (VLM) ให้ดูค่านี้เป็นหลัก\n"
            "- **อ่านครบ** — สัดส่วนบรรทัดในเฉลยที่ engine หาเจอ\n"
            "- **บรรทัดเกิน** — พ่นสิ่งที่ไม่มีในเฉลย (ลายน้ำ ลายเซ็น หรือแต่งเอง)\n"
            "- **เลขไทย strict vs lenient** — ช่องว่างระหว่างสองค่านี้บอกว่า"
            " ความผิดเรื่องตัวเลขกู้คืนได้หรือไม่"
        )

    meta = store.load_meta()
    if meta.get("versions"):
        with st.expander("เวอร์ชันที่ใช้รัน"):
            st.json({k: v for k, v in meta["versions"].items() if v})
