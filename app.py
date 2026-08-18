"""หน้าเว็บตรวจผล OCR รายหน้า

รัน:  .venv\\Scripts\\streamlit.exe run app.py

หน้าเว็บนี้อ่านผลจาก results/ อย่างเดียว ไม่รัน OCR เอง จึงกดดูซ้ำได้เร็ว
และเปลี่ยนสูตรการวัดผลแล้วเห็นผลใหม่ทันทีโดยไม่ต้องรัน OCR อีก
(รัน OCR ด้วย run_bench.py)
"""

from __future__ import annotations

import html
from dataclasses import replace
from pathlib import Path

import streamlit as st

from thai_ocr_bench import progress, store
from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR
from thai_ocr_bench.metrics import (
    Span,
    align_lines,
    compare,
    page_cer,
    thai_digit_report,
)
from thai_ocr_bench.render import PageInfo, load_pages
from thai_ocr_bench.suspect import (
    independent_peers,
    scan_page,
    thai_digit_document,
)
from thai_ocr_bench.viewer import (
    EngineRecord,
    LineRecord,
    build_html,
    encode_image,
)
from thai_ocr_bench.thai_text import THAI_DIGITS
from thai_ocr_bench.truth import (
    find_repeating_lines,
    load as load_truth,
    upsert as save_truth,
)

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


def spans_to_inner(spans: list[Span]) -> str:
    """เหมือน spans_to_html แต่ไม่มี div ครอบ — ใช้ในหน้า split view

    แยกออกมาเพราะ component ฝั่ง JS จัดโครง div เอง ต้องการแค่เนื้อใน
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
    return "".join(out)


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


def drop_watermarks(results: dict) -> dict:
    """ตัดลายน้ำและหัว/ท้ายกระดาษออกจากผลของทุก engine

    เฉลยถูกกรองบรรทัดพวกนี้ออกไปแล้วตอนสร้าง (ดู truth.find_repeating_lines)
    ถ้าไม่กรองฝั่ง OCR ด้วย ตัวที่อ่านลายน้ำเจอจะถูกลงโทษเพราะ "อ่านได้มากกว่า"
    ซึ่งกลับหัวกลับหางกับความจริง — compare_engines.py ทำแบบนี้อยู่แล้ว
    หน้าเว็บก็ต้องทำให้เหมือนกัน ไม่งั้นตัวเลขสองที่ไม่ตรงกัน

    ตัวอย่างที่เจอจริง: Typhoon อ่านหัวกระดาษ "สำนักงานคณะกรรมการกฤษฎีกา"
    ได้ครบทั้ง ๑๒ หน้า แล้วโดนนับเป็นบรรทัดเกินทุกหน้า

    ต้องตัด boxes กับ confidences ให้ตรงตำแหน่งกันด้วย
    ไม่งั้นกรอบที่หน้าเว็บวาดบนภาพจะเลื่อนไปคนละบรรทัด
    """
    cleaned: dict = {}
    for engine, pages in results.items():
        dropped = find_repeating_lines({pid: p.lines for pid, p in pages.items()})
        if not dropped:
            cleaned[engine] = pages
            continue
        cleaned[engine] = {}
        for pid, page in pages.items():
            keep = [i for i, ln in enumerate(page.lines) if ln.strip() not in dropped]
            cleaned[engine][pid] = replace(
                page,
                lines=[page.lines[i] for i in keep],
                boxes=[page.boxes[i] for i in keep if i < len(page.boxes)],
                confidences=[
                    page.confidences[i] for i in keep if i < len(page.confidences)
                ],
            )
    return cleaned


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


# ── หน้าจุดน่าสงสัย ──────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, max_entries=64)
def _crop(path: str, box: tuple[int, int, int, int], pad: int = 12) -> str | None:
    """ครอปบรรทัดเดียวออกจากภาพหน้าเต็ม แล้วคืนเป็น data URI

    เผื่อขอบไว้เล็กน้อยเพราะกรอบที่ engine ตีมักชิดตัวอักษรจนวรรณยุกต์บนล่างโดนตัด
    ซึ่งเป็นตัวที่ต้องดูที่สุดเวลาตรวจภาษาไทย
    """
    import base64
    import io

    from PIL import Image

    src = Path(path)
    if not src.exists():
        return None
    with Image.open(src) as im:
        x, y, w, h = box
        area = (max(0, x - pad), max(0, y - pad),
                min(im.width, x + w + pad), min(im.height, y + h + pad))
        crop = im.crop(area).convert("RGB")
        # ขยายให้อ่านออกบนจอ กรอบบรรทัดสูงราว ๗๐ px ซึ่งเล็กเกินกว่าจะตรวจด้วยตา
        if crop.height < 90:
            scale = 90 / crop.height
            crop = crop.resize((int(crop.width * scale), 90), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format="WEBP", quality=88)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def image_dir_for(engine: str) -> Path:
    """engine ที่ลงท้าย +clean อ่านจากภาพที่ลบลายน้ำแล้ว พิกัดจึงอิงภาพชุดนั้น"""
    return CLEAN_IMAGE_DIR if engine.endswith("+clean") else IMAGE_DIR


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
    out = []
    for pid in sorted(per_engine[engine]):
        page = {n: v[pid] for n, v in per_engine.items() if pid in v}
        out.extend(scan_page(pid, engine, page, thai_doc=thai_doc))
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
        "สองชั้น: กฎตายตัว (เลขยกกำลัง เลขอารบิกปนในเอกสารเลขไทย) "
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
    """แท็บเปรียบเทียบ — ใช้ HTML component ตัวเดียวจบ

    ฝั่ง Python ทำแค่คำนวณคะแนนแล้วเตรียมข้อมูล ส่วนการแสดงผลทั้งหมด
    (split view, ซูม/ลากรูป, scroll แยกฝั่ง, hover ไฮไลต์กรอบ, สลับโหมด)
    อยู่ใน viewer.py เพราะ Streamlit ทำสี่อย่างนั้นตรง ๆ ไม่ได้
    """
    truth = load_truth()
    have_truth = [p for p in pages if p.page_id in truth]
    if not have_truth:
        st.warning("ยังไม่มีหน้าไหนมีเฉลย ไปทำที่แท็บ 'ทำเฉลย' ก่อน")
        return

    labels = {page_label(p): p for p in have_truth}
    top = st.columns([3, 2, 1])
    picked = labels[top[0].selectbox("หน้า", list(labels), label_visibility="collapsed")]
    chosen = top[1].multiselect(
        "engine",
        sorted(results),
        default=sorted(results),
        label_visibility="collapsed",
        placeholder="เลือก engine",
    )
    tall = top[2].selectbox(
        "ความสูง", ["ปกติ", "สูง", "เต็มจอ"], label_visibility="collapsed"
    )
    height = {"ปกติ": 760, "สูง": 900, "เต็มจอ": 1100}[tall]

    image_path = IMAGE_DIR / f"{picked.page_id}.png"
    if not image_path.exists():
        st.error(f"ไม่พบไฟล์ภาพ {image_path.name}")
        return

    truth_lines = truth[picked.page_id].lines
    engines = [
        _engine_record(name, results.get(name, {}).get(picked.page_id), truth_lines)
        for name in chosen
    ]
    engines = [e for e in engines if e is not None]

    image_uri, img_w, img_h = _cached_image(str(image_path))
    st.components.v1.html(
        build_html(
            image_uri=image_uri,
            image_w=img_w,
            image_h=img_h,
            page_title=page_label(picked),
            truth_lines=truth_lines,
            engines=engines,
            height=height,
        ),
        height=height + 12,
        scrolling=False,
    )


@st.cache_data(show_spinner=False, max_entries=24)
def _cached_image(path: str) -> tuple[str, int, int]:
    """แปลงรูปเป็น data URI แล้วจำไว้ — ไม่งั้นทุกครั้งที่กดอะไรก็เข้ารหัสใหม่"""
    return encode_image(Path(path))


def _engine_record(
    name: str, stored, truth_lines: list[str]
) -> EngineRecord | None:
    """แปลงผลดิบของ engine หนึ่งตัวเป็นข้อมูลที่ component ใช้ได้"""
    if stored is None:
        return EngineRecord(
            name=name,
            notes=[{"kind": "info", "text": "ยังไม่ได้อ่านหน้านี้"}],
        )
    if not stored.ok:
        return EngineRecord(
            name=name,
            notes=[{"kind": "error", "text": f"พัง: {html.escape(str(stored.error))}"}],
        )

    score = align_lines(truth_lines, stored.lines)
    digits = thai_digit_report("\n".join(truth_lines), "\n".join(stored.lines))
    whole = page_cer(truth_lines, stored.lines)

    badges: list[dict] = []
    if score.matched_cer is not None:
        badges.append(
            {"label": f"CER บรรทัด {score.matched_cer:.1%}", "tone": cer_tone(score.matched_cer)}
        )
    if whole is not None:
        badges.append({"label": f"CER หน้า {whole:.1%}", "tone": cer_tone(whole)})
    badges.append(
        {
            "label": f"อ่านครบ {score.truth_lines - score.missed_lines}/{score.truth_lines}",
            "tone": "good" if (score.recall or 0) >= 0.95 else "bad",
        }
    )
    if score.spurious_lines:
        badges.append({"label": f"เกิน {score.spurious_lines} บรรทัด", "tone": "warn"})
    if digits["total"]:
        strict = float(digits["strict"] or 0)
        badges.append(
            {"label": f"เลขไทย {strict:.0%}", "tone": "good" if strict >= 0.9 else "bad"}
        )
    badges.append({"label": f"{stored.core_ms / 1000:.1f}s", "tone": "good"})

    notes: list[dict] = []
    loop = repeated_line(stored.lines)
    if loop:
        text, count = loop
        notes.append(
            {
                "kind": "error",
                "text": f"engine นี้ติดลูป — พ่นบรรทัดเดิมซ้ำ {count} ครั้ง ผลของหน้านี้ใช้เทียบไม่ได้",
            }
        )
    elif (ratio := merges_lines(truth_lines, stored.lines)) is not None:
        notes.append(
            {
                "kind": "info",
                "text": f"engine นี้รวมหลายบรรทัดเป็นก้อนเดียว (ยาวกว่าเฉลย {ratio:.1f} เท่า) "
                "ค่าอ่านครบจึงต่ำผิดปกติทั้งที่อ่านถูก — ให้ดู CER หน้า เป็นหลัก",
            }
        )

    def box_of(i: int | None):
        if i is None or i >= len(stored.boxes):
            return None
        return stored.boxes[i]

    def conf_of(i: int | None):
        if i is None or i >= len(stored.confidences):
            return None
        return stored.confidences[i]

    records: list[LineRecord] = []
    for pair in score.pairs:
        if pair.truth_index is not None and pair.pred_index is None:
            records.append(
                LineRecord(
                    kind="missed",
                    html="ไม่ได้อ่านบรรทัดนี้ &nbsp;<span style='opacity:.6'>("
                    + html.escape(pair.truth[:70])
                    + ")</span>",
                )
            )
        elif pair.truth_index is not None:
            display = compare(pair.truth, pair.pred, keep_spaces=True)
            records.append(
                LineRecord(
                    kind="matched",
                    html=spans_to_inner(display.spans),
                    box=box_of(pair.pred_index),
                    conf=conf_of(pair.pred_index),
                )
            )
        else:
            records.append(
                LineRecord(
                    kind="spurious",
                    html="เกินมา: " + html.escape(pair.pred[:90]),
                    box=box_of(pair.pred_index),
                    conf=conf_of(pair.pred_index),
                )
            )

    return EngineRecord(
        name=name,
        badges=badges,
        notes=notes,
        lines=records,
        has_boxes=any(b for b in stored.boxes),
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

    results = drop_watermarks(store.load())
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

    tabs = st.tabs(
        ["🔍 เปรียบเทียบ", "⚠️ จุดน่าสงสัย", "📊 สรุปผล", "✏️ ทำเฉลย", "🖼️ ตรวจภาพ"]
    )
    with tabs[0]:
        view_compare(pages, results)
    with tabs[1]:
        view_suspects(pages, results)
    with tabs[2]:
        view_summary(pages, results)
    with tabs[3]:
        view_truth(pages, results)
    with tabs[4]:
        view_images(pages)


if __name__ == "__main__":
    main()
