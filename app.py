"""หน้าเว็บตรวจผล OCR รายหน้า

รัน:  .venv\\Scripts\\streamlit.exe run app.py

หน้าเว็บนี้อ่านผลจาก results/ อย่างเดียว ไม่รัน OCR เอง จึงกดดูซ้ำได้เร็ว
และเปลี่ยนสูตรการวัดผลแล้วเห็นผลใหม่ทันทีโดยไม่ต้องรัน OCR อีก
(รัน OCR ด้วย run_bench.py)
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from thai_ocr_bench import store
from thai_ocr_bench.config import IMAGE_DIR
from thai_ocr_bench.metrics import Span, align_lines, page_cer, thai_digit_report
from thai_ocr_bench.render import PageInfo, load_pages
from thai_ocr_bench.thai_text import THAI_DIGITS
from thai_ocr_bench.truth import load as load_truth, upsert as save_truth

st.set_page_config(page_title="ตรวจผล OCR ภาษาไทย", layout="wide")

CSS = """
<style>
  .ln     { font-size:15px; line-height:2.0; word-break:break-word; }
  .ok     { color:var(--text-color); }
  .wrong  { background:#f7c1c1; color:#501313; border-radius:2px; padding:0 1px; }
  .missing{ background:#fac775; color:#412402; border-radius:2px; padding:0 1px;
            text-decoration:underline dotted; }
  .lab    { font-family:ui-monospace,Consolas,monospace; font-size:11px;
            letter-spacing:.06em; text-transform:uppercase; opacity:.6; }
  .truth  { font-size:15px; line-height:2.0; border-left:3px solid #1d3fbf;
            padding-left:10px; }
  .spur   { font-size:14px; line-height:1.9; opacity:.75; }
  .pill   { display:inline-block; font-family:ui-monospace,Consolas,monospace;
            font-size:11px; padding:1px 7px; border-radius:3px; margin-right:5px; }
  .good   { background:#e5f0ea; color:#2e6b4f; }
  .warn   { background:#f8efdc; color:#8a6212; }
  .bad    { background:#f9e9e7; color:#b4342a; }
</style>
"""


# ── ตัวช่วยแสดงผล ────────────────────────────────────────────────────────
def spans_to_html(spans: list[Span]) -> str:
    """แปลงผลการเทียบเป็น HTML ระบายสี — แดงคืออ่านผิด เหลืองคือตกหล่น"""
    out = []
    for span in spans:
        text = html.escape(span.text) or "␣"
        if span.kind == "ok":
            out.append(f'<span class="ok">{text}</span>')
        elif span.kind == "wrong":
            tip = f" (เฉลย: {html.escape(span.expected)})" if span.expected else ""
            out.append(f'<span class="wrong" title="อ่านผิด{tip}">{text}</span>')
        else:
            out.append(f'<span class="missing" title="ตกหล่น">{text}</span>')
    return f'<div class="ln">{"".join(out)}</div>'


def pill(label: str, tone: str) -> str:
    return f'<span class="pill {tone}">{html.escape(label)}</span>'


def cer_tone(cer: float | None) -> str:
    if cer is None:
        return "warn"
    return "good" if cer <= 0.02 else "warn" if cer <= 0.10 else "bad"


@st.cache_data(show_spinner=False)
def cached_pages() -> list[PageInfo]:
    return load_pages()


def page_label(p: PageInfo) -> str:
    return f"{p.doc_name} · หน้า {p.page_no}"


# ── หน้า 1 ตรวจภาพ ───────────────────────────────────────────────────────
def view_images(pages: list[PageInfo]) -> None:
    st.subheader("ตรวจภาพก่อนเริ่มวัดผล")
    st.caption(
        "ทุกหน้าต้องตั้งตรง ถ้ามีหน้าไหนตะแคงต้องแก้ก่อน "
        "เพราะภาพตะแคงจะทำให้ผลทั้งชุดพังแล้วสรุปผิดว่า engine อ่านไทยไม่ได้"
    )

    sideways = [p for p in pages if not p.portrait]
    a, b, c = st.columns(3)
    a.metric("จำนวนหน้า", len(pages))
    b.metric("ตั้งตรง", len(pages) - len(sideways))
    c.metric("ตะแคง", len(sideways), delta=None if not sideways else "ต้องแก้")

    if sideways:
        st.error("หน้าที่ยังตะแคง: " + ", ".join(p.page_id for p in sideways))

    docs = sorted({p.doc_name for p in pages})
    chosen = st.selectbox("เอกสาร", docs)
    subset = [p for p in pages if p.doc_name == chosen]

    st.write(f"`/Rotate` = {subset[0].rotation}° · {len(subset)} หน้า")
    cols = st.columns(4)
    for i, page in enumerate(subset[:16]):
        image = IMAGE_DIR / f"{page.page_id}.png"
        if image.exists():
            cols[i % 4].image(
                str(image),
                caption=f"หน้า {page.page_no} · {page.width}x{page.height}",
                use_container_width=True,
            )


# ── หน้า 2 ทำเฉลย ────────────────────────────────────────────────────────
def view_truth(pages: list[PageInfo], results: dict) -> None:
    st.subheader("ทำเฉลย")
    st.caption(
        "อ่านเทียบกับภาพจริงทุกบรรทัด ระบบซ่อนชื่อ engine ที่ใช้เป็นร่างไว้ "
        "เพื่อไม่ให้ตัวนั้นได้เปรียบตอนวัดผล"
    )

    truth = load_truth()
    labels = {page_label(p): p for p in pages}
    picked = labels[st.selectbox("หน้า", list(labels))]

    left, right = st.columns([1, 1])
    image = IMAGE_DIR / f"{picked.page_id}.png"
    if image.exists():
        left.image(str(image), use_container_width=True)

    existing = truth.get(picked.page_id)
    if existing:
        draft = existing.text
        source = "จาก text layer" if existing.source == "text_layer" else "พิมพ์เอง"
        state = "ตรวจแล้ว" if existing.reviewed else "ยังไม่ตรวจ"
        right.info(f"เฉลยเดิม: {source} · {state}")
    else:
        # ยังไม่มีเฉลย เอาผลของ engine ที่ยาวสุดมาเป็นร่างให้แก้
        candidates = [
            (len("\n".join(p.lines)), p.lines)
            for pages_of in results.values()
            if (p := pages_of.get(picked.page_id)) and p.ok
        ]
        draft = "\n".join(max(candidates)[1]) if candidates else ""
        if draft:
            right.warning("ยังไม่มีเฉลย — ด้านล่างเป็นร่างจาก OCR ต้องแก้ให้ตรงภาพ")

    edited = right.text_area("เฉลย (แก้ได้)", value=draft, height=460, key=picked.page_id)
    if right.button("บันทึกเฉลยหน้านี้", type="primary"):
        lines = [ln.strip() for ln in edited.splitlines() if ln.strip()]
        save_truth(picked.page_id, lines, source="manual", reviewed=True)
        st.success(f"บันทึกแล้ว {len(lines)} บรรทัด")
        st.rerun()


# ── หน้า 3 เปรียบเทียบ ───────────────────────────────────────────────────
def view_compare(pages: list[PageInfo], results: dict) -> None:
    st.subheader("เปรียบเทียบรายหน้า")

    truth = load_truth()
    have_truth = [p for p in pages if p.page_id in truth]
    if not have_truth:
        st.warning("ยังไม่มีหน้าไหนมีเฉลย ไปทำที่แท็บ 'ทำเฉลย' ก่อน")
        return

    labels = {page_label(p): p for p in have_truth}
    picked = labels[st.selectbox("หน้า", list(labels))]
    engines = st.multiselect(
        "engine", sorted(results), default=sorted(results)
    )
    show_spurious = st.checkbox("แสดงบรรทัดที่ OCR พ่นเกินมา (ลายน้ำ/ลายเซ็น/ขยะ)")

    st.markdown(
        f"{pill('แดง = อ่านผิด', 'bad')}{pill('เหลือง = ตกหล่น', 'warn')}"
        "  ชี้เมาส์ที่ตัวไฮไลต์เพื่อดูเฉลยของตัวนั้น",
        unsafe_allow_html=True,
    )

    image_col, text_col = st.columns([1, 2])
    image = IMAGE_DIR / f"{picked.page_id}.png"
    if image.exists():
        image_col.image(str(image), use_container_width=True)

    truth_lines = truth[picked.page_id].lines

    with text_col:
        st.markdown('<div class="lab">เฉลย</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="truth">' + "<br>".join(html.escape(t) for t in truth_lines) + "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        for name in engines:
            stored = results.get(name, {}).get(picked.page_id)
            st.markdown(f'<div class="lab">{html.escape(name)}</div>', unsafe_allow_html=True)

            if stored is None:
                st.caption("ยังไม่ได้อ่านหน้านี้")
                st.divider()
                continue
            if not stored.ok:
                st.error(f"พัง: {stored.error}")
                st.divider()
                continue

            score = align_lines(truth_lines, stored.lines)
            digits = thai_digit_report("\n".join(truth_lines), "\n".join(stored.lines))
            whole = page_cer(truth_lines, stored.lines)

            badges = pill(f"CER บรรทัด {score.matched_cer:.1%}", cer_tone(score.matched_cer)) if score.matched_cer is not None else ""
            if whole is not None:
                badges += pill(f"CER หน้า {whole:.1%}", cer_tone(whole))
            badges += pill(
                f"อ่านครบ {score.truth_lines - score.missed_lines}/{score.truth_lines}",
                "good" if (score.recall or 0) >= 0.95 else "bad",
            )
            if score.spurious_lines:
                badges += pill(f"เกิน {score.spurious_lines} บรรทัด", "warn")
            if digits["total"]:
                strict = float(digits["strict"] or 0)
                badges += pill(
                    f"เลขไทย {strict:.0%}", "good" if strict >= 0.9 else "bad"
                )
            badges += pill(f"{stored.core_ms / 1000:.1f}s", "good")
            st.markdown(badges, unsafe_allow_html=True)

            for pair in score.pairs:
                if pair.truth_index is None:
                    continue
                if pair.score is not None:
                    st.markdown(spans_to_html(pair.score.spans), unsafe_allow_html=True)

            if show_spurious:
                extra = [p.pred for p in score.pairs if p.truth_index is None]
                if extra:
                    st.markdown(
                        '<div class="spur"><b>บรรทัดเกิน:</b> '
                        + " · ".join(html.escape(e) for e in extra[:40])
                        + "</div>",
                        unsafe_allow_html=True,
                    )
            st.divider()


# ── หน้า 4 สรุปผล ────────────────────────────────────────────────────────
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
                truth_lines = truth[page.page_id].lines
                score = align_lines(truth_lines, stored.lines)
                whole = page_cer(truth_lines, stored.lines)
                if whole is not None:
                    page_cers.append(whole)
                edits += sum(s.edits for s in score.matched)
                chars += sum(s.truth_len for s in score.matched)
                missed += score.missed_lines
                found += score.truth_lines - score.missed_lines
                spurious += score.spurious_lines
                times.append(stored.core_ms / 1000)

                report = thai_digit_report("\n".join(truth_lines), "\n".join(stored.lines))
                if report["total"]:
                    n = int(report["total"])
                    d_total += n
                    d_strict += round(float(report["strict"] or 0) * n)
                    d_lenient += round(float(report["lenient"] or 0) * n)

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


# ── ประกอบหน้า ───────────────────────────────────────────────────────────
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("ตรวจผล OCR ภาษาไทย")

    pages = cached_pages()
    if not pages:
        st.error("ยังไม่มีภาพ — รัน `render_pages.py` ก่อน")
        return

    results = store.load()
    truth = load_truth()

    with st.sidebar:
        st.metric("หน้าทั้งหมด", len(pages))
        st.metric("มีเฉลยแล้ว", len(truth))
        st.metric("engine ที่มีผล", len(results))
        digits_in_truth = sum(
            t.text.count(d) for t in truth.values() for d in THAI_DIGITS
        )
        st.metric("เลขไทยในเฉลย", f"{digits_in_truth:,}")
        if not results:
            st.warning("ยังไม่มีผล OCR — รัน `run_bench.py`")

    tabs = st.tabs(["เปรียบเทียบ", "สรุปผล", "ทำเฉลย", "ตรวจภาพ"])
    with tabs[0]:
        view_compare(pages, results)
    with tabs[1]:
        view_summary(pages, results)
    with tabs[2]:
        view_truth(pages, results)
    with tabs[3]:
        view_images(pages)


if __name__ == "__main__":
    main()
