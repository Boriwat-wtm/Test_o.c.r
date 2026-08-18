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

from thai_ocr_bench import progress, store
from thai_ocr_bench.config import IMAGE_DIR
from thai_ocr_bench.metrics import (
    Span,
    align_lines,
    compare,
    page_cer,
    thai_digit_report,
)
from thai_ocr_bench.render import PageInfo, load_pages
from thai_ocr_bench.thai_text import THAI_DIGITS
from thai_ocr_bench.truth import load as load_truth, upsert as save_truth

st.set_page_config(page_title="ตรวจผล OCR ภาษาไทย", layout="wide")

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

  :root {
    --ink: #14161B;
    --ink-soft: #5B5F6B;
    --surface-2: #F5F6F8;
    --border: #E4E6EC;
    --accent: #4F46E5;
    --accent-soft: #EEF0FF;
    --radius: 0.85rem;
    --radius-sm: 0.55rem;
    --good-bg: #E6F6EC;   --good-ink: #0E7A46;
    --warn-bg: #FDF1DF;   --warn-ink: #93630A;
    --bad-bg:  #FCE7EA;   --bad-ink:  #B0123B;
    --mono: "JetBrains Mono", ui-monospace, Consolas, "Cascadia Mono", monospace;
  }

  /* ข้อความ OCR ที่ไฮไลต์จุดผิด — line-height สูงตั้งใจ ไม่ให้สระ/วรรณยุกต์ไทยที่
     ซ้อนกันสองชั้นถูกตัดขอบ */
  .ln      { font-size:15.5px; line-height:2.05; word-break:break-word; margin:.1rem 0; }
  .ok      { color:var(--ink); }
  .wrong   { background:var(--bad-bg); color:var(--bad-ink); border-radius:4px;
             padding:0 3px; box-decoration-break:clone; -webkit-box-decoration-break:clone;
             position:relative; cursor:help; }
  .missing { background:var(--warn-bg); color:var(--warn-ink); border-radius:4px;
             padding:0 3px; text-decoration:underline dotted; text-underline-offset:3px;
             box-decoration-break:clone; -webkit-box-decoration-break:clone;
             position:relative; cursor:help; }

  /* ทูลทิปตอนชี้เมาส์ที่จุดผิด/ตกหล่น — โผล่ลอยเหนือคำ ไม่ดันเนื้อหาข้างเคียง */
  .wrong::after, .missing::after {
    content:attr(data-tip); position:absolute; left:50%; bottom:calc(100% + 8px);
    transform:translateX(-50%) translateY(4px); background:var(--ink); color:#F5F6F8;
    font-size:12.5px; font-weight:500; line-height:1.55; padding:.4rem .65rem;
    border-radius:8px; white-space:normal; max-width:260px; width:max-content;
    box-shadow:0 6px 16px rgba(20,22,27,.22); opacity:0; visibility:hidden;
    pointer-events:none; transition:opacity .12s ease, transform .12s ease; z-index:60;
  }
  .wrong::before, .missing::before {
    content:""; position:absolute; left:50%; bottom:100%;
    transform:translateX(-50%) translateY(4px); border:5px solid transparent;
    border-top-color:var(--ink); opacity:0; visibility:hidden; pointer-events:none;
    transition:opacity .12s ease; z-index:60;
  }
  .wrong:hover::after, .missing:hover::after,
  .wrong:hover::before, .missing:hover::before {
    opacity:1; visibility:visible; transform:translateX(-50%) translateY(0);
  }

  /* ป้ายชื่อหัวข้อย่อย เช่น "เฉลย" ชื่อ engine — จุดสีนำหน้าแทนเส้นคั่นเรียบ ๆ */
  .lab { font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.09em;
         text-transform:uppercase; color:var(--ink-soft); margin:0 0 .5rem;
         display:flex; align-items:center; gap:.45rem; }
  .lab::before { content:""; width:6px; height:6px; border-radius:50%;
                 background:var(--accent); flex:none; }

  /* บล็อกเฉลย — การ์ดสีอ่อนคาดขอบซ้าย เด่นแยกจากผลของ engine ทันที */
  .truth { background:var(--accent-soft); border:1px solid #DCDCFB;
           border-left:4px solid var(--accent); border-radius:var(--radius);
           padding:1rem 1.15rem; font-size:15.5px; line-height:2.05; color:var(--ink); }

  /* บรรทัดที่ engine ไม่ได้อ่านเลย — การ์ดจาง ไม่ใช่ตัวหนังสือแดงลอย ๆ */
  .gone      { display:flex; gap:.5rem; align-items:baseline; background:var(--bad-bg);
               color:var(--bad-ink); border-radius:var(--radius-sm); padding:.55rem .8rem;
               font-size:14px; line-height:1.7; margin:.3rem 0; }
  .gonetruth { opacity:.65; font-size:12.5px; font-weight:400; }

  /* บรรทัดเกิน (ลายน้ำ/ลายเซ็น/ขยะ) */
  .spur { background:var(--surface-2); border:1px solid var(--border);
          border-radius:var(--radius-sm); padding:.65rem .85rem; font-size:13.5px;
          line-height:1.85; color:var(--ink-soft); margin-top:.4rem; }

  /* ป้ายตัวเลข CER / อ่านครบ / เลขไทย ฯลฯ */
  .pill { display:inline-flex; align-items:center; font-family:var(--mono);
          font-size:11.5px; font-weight:600; letter-spacing:.02em; line-height:1.3;
          white-space:nowrap; padding:.3rem .7rem; border-radius:999px;
          margin:0 .35rem .35rem 0; }
  .good { background:var(--good-bg); color:var(--good-ink); }
  .warn { background:var(--warn-bg); color:var(--warn-ink); }
  .bad  { background:var(--bad-bg);  color:var(--bad-ink); }
</style>
"""


# ── ตัวช่วยแสดงผล ────────────────────────────────────────────────────────
def spans_to_html(spans: list[Span]) -> str:
    """แปลงผลการเทียบเป็น HTML ระบายสี — แดงคืออ่านผิด เหลืองคือตกหล่น

    ใช้ data-tip + CSS แทน title ของเบราว์เซอร์ เพราะ title มีดีเลย์ก่อนขึ้น
    และสไตล์ตามแต่ระบบปฏิบัติการ ควบคุมหน้าตาให้เข้าธีมไม่ได้
    """
    out = []
    for span in spans:
        text = html.escape(span.text) or "␣"
        if span.kind == "ok":
            out.append(f'<span class="ok">{text}</span>')
        elif span.kind == "wrong":
            tip = (
                f"ควรเป็น: {html.escape(span.expected)}"
                if span.expected
                else "ส่วนเกิน — ไม่มีในเฉลย"
            )
            out.append(f'<span class="wrong" data-tip="{tip}">{text}</span>')
        else:
            out.append(
                f'<span class="missing" data-tip="ตกหล่น — engine ไม่ได้อ่านส่วนนี้">{text}</span>'
            )
    return f'<div class="ln">{"".join(out)}</div>'


def pill(label: str, tone: str) -> str:
    return f'<span class="pill {tone}">{html.escape(label)}</span>'


def cer_tone(cer: float | None) -> str:
    if cer is None:
        return "warn"
    return "good" if cer <= 0.02 else "warn" if cer <= 0.10 else "bad"


def merges_lines(truth_lines: list[str], pred_lines: list[str]) -> float | None:
    """เดาว่า engine รวมหลายบรรทัดในภาพเป็นบรรทัดเดียวหรือไม่

    VLM อย่าง Typhoon มักคืนย่อหน้าเป็นก้อนเดียวแทนที่จะแบ่งตามบรรทัดในภาพ
    เมื่อเป็นแบบนั้น ค่า "อ่านครบ" ที่คิดจากการจับคู่บรรทัดจะต่ำผิดปกติ
    ทั้งที่อ่านตัวอักษรถูก ต้องเตือนให้ไปดู CER หน้าเป็นหลักแทน

    คืนอัตราส่วนความยาวบรรทัดเฉลี่ย pred/truth ถ้ามากพอจนน่าสงสัย
    """
    t = [ln for ln in truth_lines if ln.strip()]
    p = [ln for ln in pred_lines if ln.strip()]
    if len(t) < 3 or len(p) < 1:
        return None
    avg_t = sum(len(x) for x in t) / len(t)
    avg_p = sum(len(x) for x in p) / len(p)
    if not avg_t:
        return None
    ratio = avg_p / avg_t
    return ratio if ratio >= 2.0 else None


def repeated_line(lines: list[str], threshold: int = 8) -> tuple[str, int] | None:
    """จับอาการ VLM ติดลูป — พ่นบรรทัดเดิมซ้ำจนชนเพดาน token

    เอกสารจริงไม่มีหน้าไหนที่บรรทัดเดียวกันซ้ำเกิน 8 ครั้ง ถ้าเจอแปลว่าโมเดลเสีย
    ไม่ใช่อ่านผิด ต้องบอกให้ชัดว่าผลหน้านี้ใช้เทียบไม่ได้
    """
    from collections import Counter

    counts = Counter(ln.strip() for ln in lines if ln.strip())
    if not counts:
        return None
    text, count = counts.most_common(1)[0]
    return (text, count) if count >= threshold else None


@st.cache_data(show_spinner=False)
def cached_pages() -> list[PageInfo]:
    return load_pages()


def fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 90:
        return f"{seconds:.0f} วินาที"
    return f"{seconds / 60:.0f} นาที"


@st.fragment(run_every="3s")
def progress_banner(total_pages: int) -> None:
    """แถบความคืบหน้าของตัวรัน รีเฟรชตัวเองทุก 3 วินาที

    ใช้ st.fragment เพื่อให้รีเฟรชแค่ส่วนนี้ ไม่ต้องโหลดหน้าทั้งหน้าใหม่
    ซึ่งจะทำให้ตัวเลือกหน้าและ engine ที่ผู้ใช้เลือกไว้หลุด
    """
    status = progress.load()

    # ไม่มีไฟล์สถานะ (เช่นรันด้วยโค้ดรุ่นก่อน) — เดาจากจำนวนผลที่เก็บได้
    if status is None:
        results = store.load()
        if not results:
            return
        counts = {name: len(pages) for name, pages in results.items()}
        run_size = max(counts.values()) if counts else 0
        st.caption(
            "ไม่พบไฟล์สถานะการรัน — ประมาณจากผลที่เก็บได้: "
            + " · ".join(f"{n} {c}/{run_size}" for n, c in sorted(counts.items()))
        )
        return

    if status.finished:
        note = f" ({status.failures} หน้าพัง)" if status.failures else ""
        st.success(
            f"รันเสร็จแล้ว — {len(status.done_engines)} engine × "
            f"{status.pages_total} หน้า{note}"
        )
        return

    if status.stale:
        age = status.age_seconds or 0
        st.warning(
            f"ตัวรันไม่อัปเดตมา {age / 60:.0f} นาที น่าจะหยุดไปแล้ว — "
            f"ทำได้ {len(status.done_engines)}/{len(status.engines)} engine"
        )
        return

    engine_name = status.current_engine or "กำลังเริ่ม"
    overall = status.overall_fraction

    with st.container(border=True):
        st.markdown(
            f"**กำลังรัน `{engine_name}`** &nbsp; "
            f"engine ที่ {len(status.done_engines) + 1} จาก {len(status.engines)} &nbsp;·&nbsp; "
            f"เหลืออีกประมาณ {fmt_eta(status.eta_seconds())}",
            unsafe_allow_html=True,
        )
        st.progress(
            overall,
            text=f"รวมทั้งหมด {overall:.0%}",
        )
        st.progress(
            status.engine_fraction,
            text=(
                f"{engine_name} — {status.pages_done}/{status.pages_total} หน้า"
                + (
                    f" · หน้าล่าสุดใช้ {status.last_seconds:.1f}s"
                    if status.last_seconds
                    else ""
                )
            ),
        )

        waiting = [
            e
            for e in status.engines
            if e not in status.done_engines and e != status.current_engine
        ]
        if waiting:
            st.caption("รอคิว: " + " · ".join(waiting))


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
    with st.container(border=True):
        a, b, c = st.columns(3)
        a.metric("จำนวนหน้า", len(pages))
        b.metric("ตั้งตรง", len(pages) - len(sideways))
        c.metric("ตะแคง", len(sideways), delta=None if not sideways else "ต้องแก้")

    if sideways:
        st.error("หน้าที่ยังตะแคง: " + ", ".join(p.page_id for p in sideways))

    docs = sorted({p.doc_name for p in pages})
    chosen = st.selectbox("เอกสาร", docs)
    subset = [p for p in pages if p.doc_name == chosen]

    st.caption(f"`/Rotate` = {subset[0].rotation}° · {len(subset)} หน้า")
    cols = st.columns(4)
    for i, page in enumerate(subset[:16]):
        image = IMAGE_DIR / f"{page.page_id}.png"
        if image.exists():
            with cols[i % 4]:
                with st.container(border=True):
                    st.image(
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
        with left:
            with st.container(border=True):
                st.image(str(image), use_container_width=True)

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
        with image_col:
            with st.container(border=True):
                st.image(str(image), use_container_width=True)

    truth_lines = truth[picked.page_id].lines

    with text_col:
        st.markdown('<div class="lab">เฉลย</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="truth">' + "<br>".join(html.escape(t) for t in truth_lines) + "</div>",
            unsafe_allow_html=True,
        )
        st.write("")

        for name in engines:
            stored = results.get(name, {}).get(picked.page_id)

            with st.container(border=True):
                st.markdown(f'<div class="lab">{html.escape(name)}</div>', unsafe_allow_html=True)

                if stored is None:
                    st.caption("ยังไม่ได้อ่านหน้านี้")
                    continue
                if not stored.ok:
                    st.error(f"พัง: {stored.error}")
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

                loop = repeated_line(stored.lines)
                if loop:
                    text, count = loop
                    st.error(
                        f"engine นี้ติดลูป — พ่นบรรทัดเดิมซ้ำ {count} ครั้ง "
                        f"(“{text[:50]}…”) ผลของหน้านี้ใช้เทียบไม่ได้"
                    )
                elif merges_lines(truth_lines, stored.lines):
                    ratio = merges_lines(truth_lines, stored.lines) or 0
                    st.info(
                        f"engine นี้รวมหลายบรรทัดเป็นก้อนเดียว (บรรทัดยาวกว่าเฉลย {ratio:.1f} เท่า) "
                        "ค่า “อ่านครบ” จึงต่ำผิดปกติทั้งที่อ่านถูก — ให้ดู CER หน้า เป็นหลัก"
                    )

                for pair in score.pairs:
                    if pair.truth_index is None:
                        continue
                    if pair.pred_index is None:
                        # อย่าเอาข้อความเฉลยมาแสดงเฉย ๆ เพราะจะดูเหมือนผลของ OCR
                        # ต้องบอกให้ชัดว่า engine นี้ไม่ได้อ่านบรรทัดนี้ออกมาเลย
                        st.markdown(
                            '<div class="gone">ไม่ได้อ่านบรรทัดนี้ '
                            f'<span class="gonetruth">({html.escape(pair.truth[:70])})</span>'
                            "</div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    display = compare(pair.truth, pair.pred, keep_spaces=True)
                    st.markdown(spans_to_html(display.spans), unsafe_allow_html=True)

                if show_spurious:
                    extra = [p.pred for p in score.pairs if p.truth_index is None]
                    if extra:
                        st.markdown(
                            '<div class="spur"><b>บรรทัดเกิน:</b> '
                            + " · ".join(html.escape(e) for e in extra[:40])
                            + "</div>",
                            unsafe_allow_html=True,
                        )


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
    st.caption("เทียบผล OCR แต่ละตัวกับเฉลยทีละบรรทัด — ไม่รัน OCR ในหน้านี้ อ่านผลจากไฟล์ที่ run_bench.py เก็บไว้เท่านั้น")

    pages = cached_pages()
    if not pages:
        st.error("ยังไม่มีภาพ — รัน `render_pages.py` ก่อน")
        return

    results = store.load()
    truth = load_truth()

    with st.sidebar:
        st.markdown("**สรุปชุดข้อมูล**")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.metric("หน้าทั้งหมด", len(pages))
            c2.metric("มีเฉลยแล้ว", len(truth))
            c3, c4 = st.columns(2)
            c3.metric("engine ที่มีผล", len(results))
            digits_in_truth = sum(
                t.text.count(d) for t in truth.values() for d in THAI_DIGITS
            )
            c4.metric("เลขไทยในเฉลย", f"{digits_in_truth:,}")
        if not results:
            st.warning("ยังไม่มีผล OCR — รัน `run_bench.py`")

    progress_banner(len(pages))

    tabs = st.tabs(["🔍 เปรียบเทียบ", "📊 สรุปผล", "✏️ ทำเฉลย", "🖼️ ตรวจภาพ"])
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
