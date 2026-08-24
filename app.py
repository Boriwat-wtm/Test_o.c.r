"""หน้าเว็บตรวจผล OCR รายหน้า

รัน:  .venv\\Scripts\\streamlit.exe run app.py

หน้าเว็บนี้อ่านผลจาก results/ อย่างเดียว ไม่รัน OCR เอง จึงกดดูซ้ำได้เร็ว
และเปลี่ยนสูตรการวัดผลแล้วเห็นผลใหม่ทันทีโดยไม่ต้องรัน OCR อีก
(รัน OCR ด้วย run_bench.py)
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import streamlit as st

from thai_ocr_bench import history, progress, store
from thai_ocr_bench.config import (
    CLEAN_IMAGE_DIR,
    IMAGE_DIR,
    RESULTS_DIR,
    SOURCE_DIR,
)
from thai_ocr_bench.engines.base import get_engines
from thai_ocr_bench.preprocess import clean_file
from thai_ocr_bench.metrics import (
    Span,
    align_lines,
    compare,
    page_cer,
    thai_digit_report,
)
from thai_ocr_bench.render import PageInfo, load_pages, render_all
from thai_ocr_bench.suspect import (
    independent_peers,
    rule_findings,
    scan_page,
    section_findings_by_document,
    section_suspects,
    thai_digit_document,
)
from thai_ocr_bench.viewer import (
    EngineRecord,
    LineRecord,
    build_html,
    encode_image,
)
from thai_ocr_bench.thai_text import THAI_DIGITS, normalize
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


def rule_findings_inner(line: str, *, thai_doc: bool) -> str:
    """ไฮไลต์จุดที่กฎตายตัวจับได้ (ไม่ใช้เฉลย ไม่ใช้ engine อื่น) ในแท็บเปรียบเทียบ

    ทำไมต้องมีตัวนี้แยกจาก spans_to_inner — ตัวนั้นไฮไลต์จากการเทียบกับเฉลย
    ซึ่งหน้าที่ยังไม่มีเฉลย (กรณีจริงส่วนใหญ่) จะไม่มีอะไรขึ้นเลย ทั้งที่
    suspect.rule_findings ไม่ต้องใช้เฉลยอยู่แล้ว ควรโชว์ได้ทุกหน้าไม่ว่าจะมี
    เฉลยหรือไม่ ผู้ใช้จะได้ไม่ต้องสลับไปแท็บ "จุดน่าสงสัย" เพื่อดูแค่ชั้นนี้

    ไม่รวมชั้นโหวตข้ามเครื่อง (cross_engine_findings) เพราะต้องใช้บรรทัดที่
    จัดกริดเรียบร้อยแล้วจากหน้าอื่น (peer engines ตำแหน่งเดียวกัน) ซึ่งการ์ด
    ในแท็บนี้แสดงทีละ engine อิสระจากกัน ยังไม่มีข้อมูลนั้นให้หยิบใช้
    """
    out = []
    cursor = 0
    for start, end, fix, why in rule_findings(line, thai_doc=thai_doc):
        out.append(html.escape(line[cursor:start]))
        tip = f"{why} — น่าจะเป็น: {fix}"
        out.append(f'<span class="wrong" data-tip="{html.escape(tip)}">'
                    f'{html.escape(line[start:end]) or "␣"}</span>')
        cursor = end
    out.append(html.escape(line[cursor:]))
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
    counts = Counter(ln.strip() for ln in lines if ln.strip())
    if not counts:
        return None
    text, count = counts.most_common(1)[0]
    return (text, count) if count >= threshold else None


@st.cache_data(show_spinner=False)
def cached_pages() -> list[PageInfo]:
    return load_pages()


def run_is_active(status) -> bool:
    """มีตัวรันทำงานอยู่จริงไหม — เพื่อไม่ให้กดสแกนซ้อนกันสองรอบ

    ถือว่าจบแล้วถ้าไฟล์สถานะบอกว่า finished หรือค้างจนเกิน STALE_SECONDS
    (ตัวรันตายกลางคันจะไม่ได้เขียน finished ให้ ปุ่มจะได้ไม่ล็อกค้าง)
    """
    return bool(status and not status.finished and not status.stale)


def start_scan(engines: list[str], docs: list[str], *, clean: bool, redo: bool) -> None:
    """สั่ง run_bench.py เป็นคนละโปรเซส แล้วปล่อยให้ progress_banner ตามสถานะเอง

    ไม่รัน OCR ในโปรเซสของหน้าเว็บ เพราะ engine หนักตัวจะบล็อกหน้าจนหมุนค้าง
    และ Streamlit รันสคริปต์ใหม่ทุกครั้งที่ผู้ใช้กดอะไร งานจะโดนตัดกลางคัน
    ทั้งสองฝั่งคุยกันผ่าน results/run_status.json อยู่แล้ว จึงใช้ช่องทางเดิม
    """
    # อ่านสถานะสด ๆ อีกครั้งตรงนี้ ค่าที่ปุ่มใช้ตัดสินใจมาจากตอนโหลดหน้า
    # ซึ่งอาจเก่าไปหลายวินาทีแล้ว สองโปรเซสเขียน results/ ทับกันจะได้ผลปนกัน
    if run_is_active(progress.load()):
        st.warning("มีตัวรันทำงานอยู่แล้ว ไม่สั่งซ้ำ")
        return

    cmd = [sys.executable, str(Path(__file__).parent / "run_bench.py")]
    for name in engines:
        cmd += ["-e", name]
    for name in docs:
        cmd += ["--doc", name]
    if clean:
        cmd.append("--clean")
    if redo:
        cmd.append("--redo")

    # ต่อท้าย ไม่ทับ — เดิมเปิดด้วย "w" ทำให้ log ของรอบก่อนหายทุกครั้งที่กดสแกน
    # ตอนไล่หาสาเหตุว่ารอบไหนพังเพราะอะไรจึงไม่เหลืออะไรให้ดู
    log = RESULTS_DIR / "run_bench.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    handle.write(
        f"\n{'=' * 70}\n"
        f"เริ่มรอบใหม่ {history.now_iso()}\n"
        f"  เอกสาร {', '.join(docs)}\n"
        f"  engine {', '.join(engines)}"
        f"{' · ภาพลบลายน้ำ' if clean else ''}{' · อ่านใหม่' if redo else ''}\n"
        f"{'=' * 70}\n"
    )
    handle.flush()
    # DETACHED_PROCESS ไม่ให้ตัวรันตายตาม Streamlit ตอนกด Ctrl+C หรือรีโหลด
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=log.parent.parent,
        creationflags=flags,
    )


@st.fragment(run_every="2s")
def scan_status() -> None:
    """สถานะการสแกนแบบย่อ วางไว้ใต้ปุ่มในแถบข้าง รีเฟรชตัวเองทุก 2 วินาที

    แถบใหญ่กลางหน้ามีข้อมูลครบกว่าอยู่แล้ว แต่ผู้ใช้กดปุ่มที่แถบซ้าย
    แล้วมองหาผลตรงนั้น ไม่ได้เงยไปดูกลางหน้า จึงต้องมีตัวย่อไว้ตรงจุดที่กด
    ต้องเป็น fragment ไม่งั้นค้างอยู่ที่สถานะตอนโหลดหน้าครั้งล่าสุด
    """
    status = progress.load()
    if status is None:
        return

    if status.finished:
        # done_engines นับตัวที่ถูกข้ามด้วย ถ้าดูแค่ตัวเลขนี้จะขึ้นว่า
        # "เสร็จแล้ว 100%" ทั้งที่ไม่ได้อ่านอะไรเลยสักหน้า ต้องดูประวัติรอบล่าสุด
        # ว่ามี engine ไหนได้ทำงานจริงบ้าง
        recent = history.load(limit=1)
        last = recent[0] if recent else {}
        engines = last.get("engines", [])
        ran = [e for e in engines if not e.get("skipped")]

        if engines and not ran:
            st.warning(
                f"ไม่ได้อ่านอะไรเลย — ทั้ง {len(engines)} engine มีผลของหน้าเหล่านี้"
                " อยู่แล้ว ถ้าต้องการอ่านซ้ำให้ติ๊ก **อ่านใหม่** ก่อนกด"
            )
            return

        note = f" · {status.failures} หน้าพัง" if status.failures else ""
        skipped = len(engines) - len(ran)
        skip_note = f" · ข้าม {skipped} ตัวที่มีผลแล้ว" if skipped else ""
        st.success(
            f"เสร็จแล้ว 100% — {len(ran) or len(status.done_engines)} engine × "
            f"{status.pages_total} หน้า{note}{skip_note}"
        )
        # ผลใหม่จะยังไม่โผล่จนกว่าหน้าจะโหลดใหม่ เพราะ store.load() ถูกเรียก
        # ตอนต้น main() ไปแล้ว ให้ปุ่มไว้แทนการ rerun เองเพื่อไม่ให้จอกระตุก
        if st.button("โหลดผลใหม่", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        return

    if status.stale:
        st.warning(f"ตัวรันหยุดไปแล้ว — ทำได้ {len(status.done_engines)} engine")
        return

    pct = status.overall_fraction
    st.progress(pct, text=f"{pct:.0%} · {status.current_engine or 'กำลังเริ่ม'}")
    st.caption(
        f"engine {len(status.done_engines) + 1}/{len(status.engines)} · "
        f"หน้า {status.pages_done}/{status.pages_total} · "
        f"เหลือ ~{fmt_eta(status.eta_seconds())}"
    )


def short_doc(name: str, limit: int = 22) -> str:
    """ชื่อเอกสารสั้นพอใส่แถบข้างได้ ชื่อจริงบางอันยาว 40 ตัว"""
    return name if len(name) <= limit else name[: limit - 1] + "…"


def pending_reads(
    results: dict, pages: list[PageInfo], docs: list[str], engines: list[str],
    *, clean: bool, redo: bool,
) -> tuple[int, int]:
    """(จำนวนที่จะอ่านจริง, จำนวนที่ข้ามเพราะมีผลแล้ว)

    ใช้กติกาเดียวกับ run_bench.py คือข้ามหน้าที่มีผลอยู่แล้วเว้นแต่สั่ง --redo
    ต้องคำนวณฝั่งหน้าเว็บด้วย ไม่งั้นผู้ใช้กดแล้วจบใน 0 วินาทีโดยไม่รู้ว่าทำไม
    """
    ids = [p.page_id for p in pages if p.doc_name in set(docs)]
    total = len(ids) * len(engines)
    if redo:
        return total, 0
    suffix = "+clean" if clean else ""
    done = sum(
        1
        for name in engines
        for pid in ids
        if pid in results.get(name + suffix, {})
    )
    return total - done, done


def scan_panel(pages: list[PageInfo], results: dict) -> None:
    """แผงสั่งสแกนในแถบข้าง

    ตั้งใจให้ค่าเริ่มต้นคือ "ทุกอย่าง" โดยไม่ต้องเลือก เพราะถ้า default
    เป็นรายการเต็ม multiselect จะกาง chip ทุกตัวออกมาเรียงลง กินครึ่งแถบ
    ทั้งที่ส่วนใหญ่กดรันทั้งชุดอยู่แล้ว ว่าง = ทั้งหมด
    """
    status = progress.load()
    active = run_is_active(status)

    try:
        ready, blocked = [], {}
        for engine in get_engines(None):
            ok, why = engine.available()
            if ok:
                ready.append(engine.name)
            else:
                blocked[engine.name] = why
    except Exception as exc:  # engine ที่ import ไม่ผ่านไม่ควรทำหน้าเว็บล่ม
        st.error(f"อ่านรายชื่อ engine ไม่ได้: {exc}")
        return

    names = sorted(ready)
    docs = sorted({p.doc_name for p in pages})
    count = Counter(p.doc_name for p in pages)

    # ไฟล์ที่เพิ่งวางในโฟลเดอร์ต้นทางยังไม่มีภาพ และหน้าเว็บ cache รายการหน้าไว้
    # จึงไม่โผล่จนกว่าจะ render แล้วล้าง cache ซึ่งเดิมต้องออกไปพิมพ์เองใน terminal
    new_pdfs = sorted(
        p.stem for p in SOURCE_DIR.glob("*.pdf")
        if p.stem not in {pg.doc_name for pg in pages}
    ) if SOURCE_DIR.exists() else []
    if new_pdfs:
        st.warning(
            f"มี {len(new_pdfs)} ไฟล์ในโฟลเดอร์ต้นทางที่ยังไม่ได้แปลงเป็นภาพ:\n\n- "
            + "\n- ".join(short_doc(n, 30) for n in new_pdfs)
        )
    if st.button(
        "อ่านไฟล์ใหม่จากโฟลเดอร์ต้นทาง",
        use_container_width=True,
        type="primary" if new_pdfs else "secondary",
    ):
        with st.spinner("กำลังแปลง PDF เป็นภาพ…"):
            render_all()
            for page in load_pages():
                src = IMAGE_DIR / f"{page.page_id}.png"
                if src.exists():
                    clean_file(src, CLEAN_IMAGE_DIR / f"{page.page_id}.png")
        st.cache_data.clear()  # ไม่งั้นรายการหน้ายังเป็นชุดเดิมที่จำไว้
        st.rerun()

    st.subheader("สั่งสแกน", divider="gray")
    pick_docs = st.multiselect(
        "เอกสาร",
        docs,
        placeholder=f"ทุกเอกสาร ({len(docs)})",
        format_func=lambda d: f"{short_doc(d)} · {count[d]}",
    )
    pick_engines = st.multiselect(
        "engine", names, placeholder=f"ทุก engine ที่พร้อม ({len(names)})"
    )

    a, b = st.columns(2)
    clean = a.checkbox("ภาพลบลายน้ำ", value=False)
    redo = b.checkbox("อ่านใหม่", value=False)

    use_docs = pick_docs or docs
    use_engines = pick_engines or names
    todo, skip = pending_reads(
        results, pages, use_docs, use_engines, clean=clean, redo=redo
    )

    # ปุ่มต้องโผล่เสมอแม้กดไม่ได้ ถ้า return ทิ้งตอนไม่มี engine
    # ผู้ใช้จะหาปุ่มไม่เจอแล้วนึกว่าฟีเจอร์ไม่มีอยู่จริง
    if active:
        st.button("กำลังสแกนอยู่…", disabled=True, use_container_width=True)
    elif not names:
        st.button("เริ่มสแกน", disabled=True, use_container_width=True)
        st.caption("ยังไม่มี engine พร้อมใช้ — `uv sync --extra all`")
    elif todo == 0:
        # กดไปก็ข้ามหมดแล้วจบใน 0 วินาที ต้องบอกก่อนไม่ใช่ปล่อยให้กดแล้วงง
        st.button("เริ่มสแกน", disabled=True, use_container_width=True)
        st.caption(f"มีผลครบแล้วทั้ง {skip:,} ครั้ง — ติ๊ก **อ่านใหม่** ถ้าต้องการอ่านซ้ำ")
    else:
        note = f" · ข้าม {skip:,} ที่มีผลแล้ว" if skip else ""
        st.caption(f"จะอ่าน {todo:,} ครั้ง{note}")
        if st.button("เริ่มสแกน", type="primary", use_container_width=True):
            start_scan(use_engines, use_docs, clean=clean, redo=redo)
            st.rerun()

    scan_status()

    # ข้อมูลอ้างอิง ไม่ใช่ตัวควบคุม จึงอยู่ล่างสุดและพับไว้
    if blocked:
        with st.expander(f"อีก {len(blocked)} engine ยังใช้ไม่ได้"):
            for name, why in sorted(blocked.items()):
                st.caption(f"**{name}** — {why}")


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

    # เลือกได้ทุกหน้า ไม่ใช่เฉพาะหน้าที่มีเฉลย เฉลยสร้างอัตโนมัติจาก text layer
    # ไฟล์สแกนจึงไม่มี แล้วเคยหายไปจากช่องเลือกเงียบ ๆ ทั้งที่ยังดูผลเทียบกับภาพได้
    # หน้าที่ไม่มีเฉลยจะแสดงข้อความที่อ่านได้โดยไม่มีคะแนน
    #
    # แยกเอกสารกับหน้าเป็นคนละช่อง เฉพาะแท็บนี้ เพราะเป็นแท็บที่ต้องสลับหน้าถี่สุด
    # รวมเป็นช่องเดียวแล้วทุกบรรทัดขึ้นต้นด้วยชื่อเอกสารซ้ำกัน ต่างแค่เลขหน้าท้ายสุด
    docs = sorted({p.doc_name for p in pages})
    per_doc = Counter(p.doc_name for p in pages)

    top = st.columns([2.6, 1.25, 0.34, 0.34, 2.1, 0.95])
    doc = top[0].selectbox(
        "เอกสาร",
        docs,
        format_func=lambda d: f"{d}  ({per_doc[d]} หน้า)",
        label_visibility="collapsed",
        key="cmp_doc",
    )
    subset = [p for p in pages if p.doc_name == doc]
    page_labels = {
        f"หน้า {p.page_no}" + ("" if p.page_id in truth else "  ·  ยังไม่มีเฉลย"): p
        for p in subset
    }
    keys = list(page_labels)

    # ปุ่มเลื่อนหน้าต้องมาก่อน selectbox ในลำดับโค้ด แม้จะแสดงผลอยู่ถัดไปทางขวา
    # (คอลัมน์คุมตำแหน่งที่วาด ส่วนลำดับโค้ดคุมลำดับการทำงาน)
    #
    # เพราะทางเดียวที่จะเปลี่ยนค่าของ selectbox ที่มี key ได้ คือเขียน
    # st.session_state["cmp_page"] ก่อนที่ widget จะถูกสร้างในรอบนั้น
    # เขียนทีหลังจะโยน StreamlitAPIException ส่วนการส่ง index= ก็ไม่มีผล
    # เพราะเมื่อ widget มี key แล้ว Streamlit จะใช้ค่าที่จำไว้ทับ index เสมอ
    # (ลองมาแล้วทั้งสองแบบ แบบแรกพัง แบบหลังกดแล้วหน้าไม่ขยับ)
    if st.session_state.get("cmp_page") not in keys:
        st.session_state.pop("cmp_page", None)  # เปลี่ยนเอกสารแล้วรายการหน้าเปลี่ยนตาม
    here = keys.index(st.session_state.get("cmp_page", keys[0]))

    if top[2].button("‹", disabled=here == 0, use_container_width=True,
                     help="หน้าก่อนหน้า"):
        st.session_state["cmp_page"] = keys[here - 1]
        st.rerun()
    if top[3].button("›", disabled=here >= len(keys) - 1, use_container_width=True,
                     help="หน้าถัดไป"):
        st.session_state["cmp_page"] = keys[here + 1]
        st.rerun()

    picked_label = top[1].selectbox(
        "หน้า", keys, label_visibility="collapsed", key="cmp_page"
    )
    picked = page_labels[picked_label]
    # ว่าง = ทุกตัว เหมือนแผงสั่งสแกน ถ้า default เป็นรายการเต็ม
    # มันจะกาง chip ทั้ง 8 ตัวอัดอยู่ในคอลัมน์แคบ ๆ จนบังแถวควบคุมทั้งแถว
    all_engines = sorted(results)
    chosen = (
        top[4].multiselect(
            "engine",
            all_engines,
            label_visibility="collapsed",
            placeholder=f"ทุก engine ({len(all_engines)})",
        )
        or all_engines
    )
    tall = top[5].selectbox(
        "ความสูง", ["ปกติ", "สูง", "เต็มจอ"], label_visibility="collapsed"
    )
    height = {"ปกติ": 760, "สูง": 900, "เต็มจอ": 1100}[tall]

    image_path = IMAGE_DIR / f"{picked.page_id}.png"
    if not image_path.exists():
        st.error(f"ไม่พบไฟล์ภาพ {image_path.name}")
        return

    entry = truth.get(picked.page_id)
    truth_lines = entry.lines if entry else []
    if not truth_lines:
        st.info(
            "หน้านี้ยังไม่มีเฉลย จึงไม่มีคะแนน — เทียบข้อความกับภาพด้วยตาได้ "
            "หรือไปสร้างเฉลยที่แท็บ 'ทำเฉลย'"
        )
    engines = [
        _engine_record(name, results.get(name, {}).get(picked.page_id), truth_lines)
        for name in chosen
    ]
    engines = [e for e in engines if e is not None]

    image_uri, img_w, img_h = cached_image(image_path)
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

    page_round_history(picked.page_id)


def text_stats(lines: list[str]) -> dict:
    """ตัวเลขสรุปของข้อความหนึ่งชุด — ตัวที่งานนี้สนใจจริงคือเลขไทย"""
    text = "".join(lines)
    return {
        "lines": len(lines),
        "chars": len(text),
        "thai_digits": sum(text.count(d) for d in THAI_DIGITS),
        "arabic_digits": sum(text.count(d) for d in "0123456789"),
    }


def diff_note(current: list[str], previous: list[str] | None) -> str:
    """ต่างจากรอบก่อนแค่ไหน — เทียบหลัง normalize เพื่อไม่ให้ช่องว่างนับเป็นความต่าง"""
    if previous is None:
        return "รอบแรกของ engine นี้"
    from rapidfuzz.distance import Levenshtein

    a, b = normalize("\n".join(current)), normalize("\n".join(previous))
    if a == b:
        return "เหมือนรอบก่อนทุกตัวอักษร"
    sim = Levenshtein.normalized_similarity(a, b)
    return f"ต่างจากรอบก่อน {1 - sim:.1%}"


def page_round_history(page_id: str) -> None:
    """ประวัติการอ่านหน้านี้ทีละรอบ

    วางไว้ใต้ split view ไม่ยัดเข้าไปในนั้น เพราะ component ข้างบนออกแบบมา
    สำหรับเทียบผลล่าสุดกับภาพ ส่วนตรงนี้คือเทียบรอบต่อรอบ คนละคำถามกัน

    ต้องบอกให้ครบว่า "รอบนั้นใช้อะไรอ่าน แล้วได้อะไรมา" ไม่ใช่พ่นข้อความดิบ
    เพราะพอมีหลายรอบแล้วจำไม่ได้ว่ารอบไหนใช้ภาพลบลายน้ำ รอบไหนใช้ภาพดิบ
    """
    rows = history.load_page(page_id)
    if not rows:
        with st.expander("ประวัติการอ่านหน้านี้"):
            st.caption(
                "ยังไม่มีประวัติของหน้านี้ — เริ่มบันทึกตั้งแต่รอบถัดไปที่กดสแกน "
                "ผลที่เห็นข้างบนมาจาก `ocr_results.json` ซึ่งเก็บแค่ผลล่าสุด"
            )
        return

    order = history.run_order()
    runs_meta = {r.get("started_at"): r for r in history.load()}

    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)

    # ผลรอบก่อนหน้าของ engine เดียวกัน ใช้ตอบว่า "รอบนี้ต่างจากรอบก่อนไหม"
    # rows เรียงใหม่ไปเก่า จึงต้องไล่จากท้ายมาหน้าเพื่อให้ "ก่อนหน้า" ถูกต้อง
    previous: dict[tuple[str, str], list[str]] = {}
    seen: dict[str, list[str]] = {}
    for r in reversed(rows):
        key = (r["run"], r["engine"])
        if r["engine"] in seen:
            previous[key] = seen[r["engine"]]
        seen[r["engine"]] = r["lines"]

    with st.expander(f"ประวัติการอ่านหน้านี้ — {len(by_run)} รอบ", expanded=False):
        labels = {}
        for run in by_run:  # rows เรียงล่าสุดก่อนอยู่แล้ว dict จึงคงลำดับนั้น
            no = order.get(run)
            stamp = run.replace("T", " ").replace("+00:00", "")[5:16]
            labels[f"รอบที่ {no or '?'} · {stamp} · {len(by_run[run])} engine"] = run

        pick = st.radio(
            "เลือกรอบ", list(labels), horizontal=False, label_visibility="collapsed"
        )
        run_key = labels[pick]
        chosen = by_run[run_key]
        meta = runs_meta.get(run_key, {})

        # หัวข้อรอบ — บอกว่าใช้อะไรอ่าน
        source = "ภาพลบลายน้ำ (`data/cleaned`)" if meta.get("clean") else "ภาพดิบ (`data/images`)"
        bits = [f"**ใช้** {source}"]
        if meta.get("redo"):
            bits.append("**อ่านใหม่ทับของเก่า**")
        if meta.get("duration_s"):
            bits.append(f"**รอบนี้ใช้เวลารวม** {meta['duration_s'] / 60:.1f} นาที")
        if meta.get("pages"):
            ran = len([e for e in meta.get("engines", []) if not e.get("skipped")])
            bits.append(f"**ทั้งรอบ** {ran} engine × {meta['pages']} หน้า")
        st.markdown(" &nbsp;·&nbsp; ".join(bits))

        table = []
        for r in chosen:
            s = text_stats(r["lines"])
            table.append(
                {
                    "engine": r["engine"],
                    "บรรทัด": s["lines"],
                    "ตัวอักษร": f"{s['chars']:,}",
                    "เลขไทย": s["thai_digits"],
                    "เลขอารบิก": s["arabic_digits"],
                    "วินาที": f"{r['ms'] / 1000:.1f}",
                    "เทียบรอบก่อน": diff_note(
                        r["lines"], previous.get((r["run"], r["engine"]))
                    ),
                    "สถานะ": "เสร็จ" if r["ok"] else f"พัง: {r.get('error')}",
                }
            )
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.caption(
            "เลขอารบิกในเอกสารเลขไทยคืออาการอ่านผิดที่งานนี้วัดโดยตรง "
            "ตัวเลขสองคอลัมน์นี้จึงบอกได้เร็วกว่าอ่านข้อความเอง"
        )

        for r in chosen:
            s = text_stats(r["lines"])
            head = (
                f"{r['engine']} — {s['lines']} บรรทัด · {s['chars']:,} ตัวอักษร"
                f" · เลขไทย {s['thai_digits']}"
            )
            with st.expander(head):
                st.code("\n".join(r["lines"]) or "(ไม่มีข้อความ)")


@st.cache_data(show_spinner=False, max_entries=24, persist="disk")
def _cached_image(path: str, mtime: float) -> tuple[str, int, int]:
    """แปลงรูปเป็น data URI แล้วจำไว้ — ไม่งั้นทุกครั้งที่กดอะไรก็เข้ารหัสใหม่

    วัดแล้วขั้นนี้ใช้ 469 ms ต่อหน้า ซึ่งเป็น 90% ของเวลาที่รอตอนเปลี่ยนหน้า
    (ย่อ 2480x3508 แล้วเข้ารหัส WebP) แคชเดิมอยู่ในหน่วยความจำอย่างเดียว
    จึงหายทุกครั้งที่รีสตาร์ท และตอนไล่ตรวจทีละหน้าจะเสียเวลานี้ทุกหน้าใหม่

    persist="disk" ทำให้หน้าที่เคยเปิดแล้วเร็วทันทีข้ามรอบการรัน
    ส่ง mtime เข้ามาด้วยเพื่อให้แคชหมดอายุเองเมื่อ render ภาพใหม่
    """
    return encode_image(Path(path))


def cached_image(path: Path) -> tuple[str, int, int]:
    stamp = path.stat().st_mtime if path.exists() else 0.0
    return _cached_image(str(path), stamp)



CLEAN_SUFFIX = "+clean"


def engine_group(name: str) -> tuple[str, str]:
    """(ตระกูล, ป้ายภาพต้นทาง) — ผลของ engine เดียวกันคนละภาพควรอยู่ด้วยกัน

    run_bench.py ตั้งชื่อผลเป็น <engine>+clean เมื่อรันกับภาพที่ลบลายน้ำแล้ว
    ฝั่งแสดงผลจึงแยกกลับออกมาได้จากชื่อ ไม่ต้องเก็บข้อมูลเพิ่ม
    """
    if name.endswith(CLEAN_SUFFIX):
        return name[: -len(CLEAN_SUFFIX)], "ลบลายน้ำแล้ว"
    return name, "ภาพดิบ"


def _unscored_record(name: str, stored) -> EngineRecord:
    """ผลของ engine บนหน้าที่ยังไม่มีเฉลย — ข้อความล้วน ไม่มีคะแนน

    ห้ามเรียก align_lines ด้วยเฉลยว่าง เพราะทุกบรรทัดจะกลายเป็น "เกินมา"
    แล้วป้ายจะขึ้น "อ่านครบ 0/0" กับ "เกิน N บรรทัด" ซึ่งอ่านแล้วเข้าใจผิด
    ว่า engine พัง ทั้งที่เราแค่ยังไม่มีอะไรให้เทียบ
    """
    badges = [
        {"label": f"{len(stored.lines)} บรรทัด", "tone": "good"},
        {"label": f"{stored.core_ms / 1000:.1f}s", "tone": "good"},
    ]
    notes = [{"kind": "info", "text": "ยังไม่มีเฉลยหน้านี้ — แสดงข้อความที่อ่านได้ ไม่มีคะแนน"}]

    loop = repeated_line(stored.lines)
    if loop:
        text, count = loop
        notes.append(
            {
                "kind": "error",
                "text": f"engine นี้ติดลูป — พ่นบรรทัดเดิมซ้ำ {count} ครั้ง",
            }
        )

    thai_doc = thai_digit_document(stored.lines)
    lines = [
        LineRecord(
            kind="matched",
            html=rule_findings_inner(line, thai_doc=thai_doc),
            box=stored.boxes[i] if i < len(stored.boxes) else None,
            conf=stored.confidences[i] if i < len(stored.confidences) else None,
        )
        for i, line in enumerate(stored.lines)
    ]
    group, variant = engine_group(name)
    return EngineRecord(
        name=name,
        group=group,
        variant=variant,
        badges=badges,
        notes=notes,
        lines=lines,
        has_boxes=any(b for b in stored.boxes),
    )


def _engine_record(
    name: str, stored, truth_lines: list[str]
) -> EngineRecord | None:
    """แปลงผลดิบของ engine หนึ่งตัวเป็นข้อมูลที่ component ใช้ได้

    truth_lines ว่างได้ หน้าที่ยังไม่มีเฉลยจะแสดงข้อความที่อ่านได้เฉย ๆ
    โดยไม่มีคะแนน ดีกว่าซ่อนทั้งหน้าเพราะยังเอาไปเทียบกับภาพด้วยตาได้
    """
    if stored is None:
        group, variant = engine_group(name)
        return EngineRecord(
            name=name,
            group=group,
            variant=variant,
            notes=[{"kind": "info", "text": "ยังไม่ได้อ่านหน้านี้"}],
        )
    if not stored.ok:
        group, variant = engine_group(name)
        return EngineRecord(
            name=name,
            group=group,
            variant=variant,
            notes=[{"kind": "error", "text": f"พัง: {html.escape(str(stored.error))}"}],
        )

    if not truth_lines:
        return _unscored_record(name, stored)

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

    group, variant = engine_group(name)
    return EngineRecord(
        name=name,
        group=group,
        variant=variant,
        badges=badges,
        notes=notes,
        lines=records,
        has_boxes=any(b for b in stored.boxes),
    )


# ── หน้า 4 สรุปผล ────────────────────────────────────────────────────────
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


# ── หน้าประวัติการรัน ────────────────────────────────────────────────────
def view_history() -> None:
    st.subheader("ประวัติการรัน")
    st.caption(
        "หนึ่งแถวคือหนึ่งรอบที่กดสแกน เรียงจากรอบล่าสุดลงไป "
        "เก็บที่ `results/run_history.jsonl` ต่อท้ายอย่างเดียว ไม่เขียนทับ"
    )

    rows = history.load()
    if not rows:
        st.info(
            "ยังไม่มีประวัติ — เริ่มบันทึกตั้งแต่รอบถัดไปที่กดสแกน "
            "รอบก่อนหน้านี้ไม่ได้ถูกเก็บไว้เพราะยังไม่มีระบบนี้"
        )
        return

    st.caption(f"ทั้งหมด {len(rows)} รอบ")
    for i, run in enumerate(rows):
        no = len(rows) - i  # รอบที่ 1 คือรอบแรกสุดตามลำดับเวลา
        stamp = run.get("started_at", "?").replace("T", " ").replace("+00:00", "")
        ok = run.get("completed", False)
        head = f"{'✅' if ok else '⚠️'} รอบที่ {no} · {stamp} · {history.summarize(run)}"

        with st.expander(head, expanded=(i == 0)):
            engines_all = run.get("engines", [])
            ran = [e for e in engines_all if not e.get("skipped")]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("อ่านจริง", f"{sum(e.get('pages', 0) for e in ran):,} ครั้ง")
            c2.metric("บรรทัดที่ได้", f"{sum(e.get('lines', 0) for e in ran):,}")
            c3.metric("เวลา", f"{run.get('duration_s', 0) / 60:.1f} นาที")
            c4.metric("หน้าพัง", sum(e.get("failures", 0) for e in ran))

            source = "ภาพลบลายน้ำ" if run.get("clean") else "ภาพดิบ"
            flags = [f"ใช้{source}"]
            if run.get("redo"):
                flags.append("อ่านใหม่ทับของเก่า")
            if len(engines_all) - len(ran):
                flags.append(f"ข้าม {len(engines_all) - len(ran)} engine ที่มีผลแล้ว")
            if not ok:
                flags.append("**รอบนี้ไม่จบ — หยุดกลางคัน**")
            st.markdown(
                f"**เอกสาร** {' · '.join(run.get('docs', [])) or '-'} "
                f"({run.get('pages', 0)} หน้า)  \n"
                f"**สั่งด้วย** {' · '.join(flags)}"
            )

            table = []
            for e in run.get("engines", []):
                if e.get("skipped"):
                    table.append(
                        {"engine": e["name"], "หน้า": "-", "บรรทัด": "-",
                         "พัง": "-", "วินาที": "-", "สถานะ": "ข้าม (มีผลครบแล้ว)"}
                    )
                else:
                    table.append(
                        {
                            "engine": e["name"],
                            "หน้า": e.get("pages", 0),
                            "บรรทัด": f"{e.get('lines', 0):,}",
                            "พัง": e.get("failures", 0),
                            "วินาที": f"{e.get('seconds', 0):.1f}",
                            "สถานะ": "เสร็จ",
                        }
                    )
            if table:
                st.dataframe(table, use_container_width=True, hide_index=True)
            else:
                st.caption("ไม่มี engine ไหนได้รันในรอบนี้")

    log = RESULTS_DIR / "run_bench.log"
    if log.exists():
        with st.expander("log ดิบของตัวรัน (ท้ายไฟล์)"):
            text = log.read_text(encoding="utf-8", errors="replace")
            st.code(text[-8000:] or "(ว่าง)")


# ── หน้าอ่านซ้ำแบบซูม ────────────────────────────────────────────────────
def start_rescue(engine: str, limit: int | None) -> None:
    """สั่ง rescue.py เป็นคนละโปรเซส แบบเดียวกับปุ่มสแกน

    ต้องแยกโปรเซสเพราะการอ่านซ้ำยิง API ทีละจุดโดยมี throttle 3.1 วินาที
    ถ้ารันในโปรเซสของหน้าเว็บจะบล็อกจนหน้าหมุนค้างเป็นนาที
    """
    cmd = [sys.executable, str(Path(__file__).parent / "rescue.py"), "--engine", engine]
    if limit:
        cmd += ["--limit", str(limit)]

    log = RESULTS_DIR / "rescue.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    handle.write(f"\n{'=' * 70}\nเริ่มอ่านซ้ำ {history.now_iso()} · engine {engine}\n")
    handle.flush()
    subprocess.Popen(
        cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=log.parent.parent,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def rescue_controls(results: dict) -> None:
    """แผงสั่งอ่านซ้ำ — วางไว้บนสุดของแท็บ ไม่ต้องออกไปพิมพ์คำสั่งเอง"""
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1.2, 1.4])
        names = sorted(results)
        if not names:
            st.caption("ยังไม่มีผล OCR ให้อ่านซ้ำ — สแกนก่อน")
            return
        # ตัวที่แม่นสุดคุ้มสุดที่จะอ่านซ้ำ เพราะจุดที่มันยังผิดคือจุดที่ยากจริง
        default = next((i for i, n in enumerate(names) if "num" in n), 0)
        engine = c1.selectbox("engine ที่จะให้อ่านซ้ำ", names, index=default)
        limit = c2.number_input("จำกัดจุด", min_value=0, max_value=999, value=0,
                                help="0 = ไม่จำกัด ใส่เลขไว้ลองก่อนได้")
        c3.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        if c3.button("เริ่มอ่านซ้ำ", type="primary", use_container_width=True):
            start_rescue(engine, int(limit) or None)
            st.success("สั่งแล้ว — กดโหลดใหม่อีกครั้งเมื่อรันเสร็จ")


def view_rescue(pages: list[PageInfo], results: dict) -> None:
    st.subheader("จุดที่อ่านซ้ำแบบซูม")
    st.caption(
        "จุดที่ตัวคัดสงสัยว่าอ่านผิด ถูกครอปออกมาขยาย 4 เท่าแล้วส่งให้อ่านใหม่ "
        "ผลอยู่ที่นี่เพื่อให้ตัดสินทีละจุด ไม่ได้เขียนทับผลเดิมอัตโนมัติ"
    )

    rescue_controls(results)

    path = RESULTS_DIR / "rescue.json"
    if not path.exists():
        st.info("ยังไม่มีผลอ่านซ้ำ — เลือก engine ด้านบนแล้วกดเริ่มอ่านซ้ำ")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    engine = data.get("engine", "?")
    if not items:
        st.info("ไฟล์มีอยู่แต่ไม่มีจุดไหนถูกอ่านซ้ำ")
        return

    changed = [r for r in items if r.get("changed")]
    failed = [r for r in items if r.get("error")]

    c1, c2, c3 = st.columns(3)
    c1.metric("จุดที่อ่านซ้ำ", len(items))
    c2.metric("ข้อความเปลี่ยน", len(changed))
    c3.metric("อ่านไม่สำเร็จ", len(failed))
    st.caption(f"engine ที่ใช้อ่านซ้ำ: `{engine}`")

    only_changed = st.checkbox("แสดงเฉพาะจุดที่ข้อความเปลี่ยน", value=True)
    shown = changed if only_changed else items
    if not shown:
        st.success("อ่านซ้ำแล้วไม่มีจุดไหนเปลี่ยน — ผลเดิมน่าจะถูกอยู่แล้ว")
        return

    byid = {p.page_id: p for p in pages}
    for i, r in enumerate(shown):
        page = byid.get(r["page_id"])
        label = page_label(page) if page else r["page_id"]
        head = f"{label} · บรรทัดที่ {r['grid_line'] + 1}"
        with st.expander(head, expanded=(i == 0)):
            # ครอปด้วยกรอบเดียวกับที่ rescue ใช้ จะได้เห็นสิ่งที่ engine เห็นตอนอ่านซ้ำ
            img = _crop(str(IMAGE_DIR / f"{r['page_id']}.png"), tuple(r["box"]), pad=24)
            if img:
                st.markdown(
                    f'<img src="{img}" style="width:100%;border:1px solid #E4E6EC;'
                    f'border-radius:8px" alt="ภาพบรรทัดที่อ่านซ้ำ">',
                    unsafe_allow_html=True,
                )
            a, b = st.columns(2)
            a.markdown("**เดิม** (อ่านรวมทั้งหน้า)")
            a.code(r["before"] or "(ว่าง)")
            b.markdown("**อ่านซ้ำ** (ครอป · ขยาย 4 เท่า)")
            b.code(r["after"] or "(ว่าง)")
            if r.get("error"):
                st.error(f"อ่านซ้ำไม่สำเร็จ: {r['error']}")

    if st.button("โหลดผลอ่านซ้ำใหม่"):
        st.rerun()
    st.caption(
        "ยังไม่มีปุ่มรับผลอ่านซ้ำเข้าไปแทนที่ของเดิม เพราะข้อความเดิมเป็นส่วนที่หั่นตามกริด "
        "ซึ่งบางครั้งกินยาวกว่าบรรทัดจริงในภาพ แทนที่ตรง ๆ แล้ววัดได้ว่าทำข้อความหาย"
    )


# ── ประกอบหน้า ───────────────────────────────────────────────────────────
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("ตรวจผล OCR ภาษาไทย")
    st.caption(
        "เทียบผล OCR แต่ละตัวกับเฉลยทีละบรรทัด — สั่งสแกนได้จากแถบซ้าย "
        "ตัวรันเป็นคนละโปรเซส ปิดหน้านี้ระหว่างรันได้"
    )

    pages = cached_pages()
    if not pages:
        st.error("ยังไม่มีภาพ — รัน `render_pages.py` ก่อน")
        return

    results = drop_watermarks(store.load())
    truth = load_truth()

    with st.sidebar:
        # เมตริกแถวเดียวสามช่อง สี่ช่องสองแถวสูงเกินไปสำหรับแถบแคบ ๆ
        # ส่วนที่เหลือเป็นตัวเลขอ้างอิง ยัดเป็น caption บรรทัดเดียวพอ
        st.subheader("ชุดข้อมูล", divider="gray")
        c1, c2, c3 = st.columns(3)
        c1.metric("หน้า", len(pages))
        c2.metric("มีเฉลย", len(truth))
        c3.metric("engine", len(results))

        digits_in_truth = sum(
            t.text.count(d) for t in truth.values() for d in THAI_DIGITS
        )
        st.caption(
            f"เลขไทยในเฉลย {digits_in_truth:,} ตัว · "
            f"ยังไม่มีเฉลย {len(pages) - len(truth)} หน้า"
        )
        if not results:
            st.warning("ยังไม่มีผล OCR — กดสแกนด้านล่าง")

        scan_panel(pages, results)

    progress_banner(len(pages))

    tabs = st.tabs(
        [
            "🔍 เปรียบเทียบ",
            "⚠️ จุดน่าสงสัย",
            "📊 สรุปผล",
            "✏️ ทำเฉลย",
            "🖼️ ตรวจภาพ",
            "🔎 อ่านซ้ำแบบซูม",
            "🧾 ประวัติการรัน",
        ]
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
    with tabs[5]:
        view_rescue(pages, results)
    with tabs[6]:
        view_history()


if __name__ == "__main__":
    main()
