"""หน้าตาส่วนกลางของหน้าเว็บ — CSS กับตัวช่วยเรนเดอร์ข้อความที่ไฮไลต์แล้ว

แยกออกจาก view เพราะทุกแท็บใช้ชุดสีและชุดคลาสเดียวกัน ถ้าปล่อยให้แต่ละแท็บ
นิยามเอง สีของ "ผิด/ตกหล่น/ดี" จะเพี้ยนกันเองเมื่อแก้ทีละที่
"""

from __future__ import annotations

import html

from ..metrics import Span
from ..suspect import rule_findings

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');

  :root {
    --ink: #14161B;
    --ink-soft: #5B5F6B;
    --paper: #FFFFFF;
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

    /* สีของ "ชนิดจุดที่ต้องตรวจ" — ใช้ร่วมกันระหว่างกรอบบนภาพกับข้อความ
       ถ้าสองฝั่งใช้คนละชุด คนจะจับคู่กรอบกับบรรทัดไม่ได้ ซึ่งเป็นหัวใจของหน้าตรวจงาน */
    --rv-digit: #4F46E5;  --rv-digit-bg: #EEF0FF;
    --rv-mixed: #B0123B;  --rv-mixed-bg: #FCE7EA;
    --rv-shaky: #B45309;  --rv-shaky-bg: #FDF1DF;
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


