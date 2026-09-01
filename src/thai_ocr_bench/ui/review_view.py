"""แท็บตรวจงาน — ภาพซ้ายมีกรอบชี้จุด ข้อความขวาแก้ได้ทันที

รวมสองสัญญาณที่วัดแล้วว่าคุ้มที่สุด (ดูเหตุผลเต็มใน review.py)
  ตัวเลข       ดู 2.8% ของหน้า ครอบคลุมความผิด 45%
  ความไม่นิ่ง   จับของที่โมเดลแต่งเอง ซึ่งตัวเลขจับไม่ได้

ต่างจากแท็บ "จุดน่าสงสัย" ตรงที่ไม่พึ่ง engine อื่นมาตัดสินข้อความ
วัดแล้วการโหวตข้าม engine จับผิดได้แค่ 2% เพราะเอาตัวที่แม่นน้อยกว่า
มาตัดสินตัวที่แม่นที่สุด ตรงนี้ engine อื่นมีหน้าที่เดียวคือบอกพิกัด

หลักการจัดหน้า: สีหนึ่งสีมีความหมายเดียวทั้งหน้า และความหมายนั้นเขียนไว้
ให้อ่านได้ตลอดเวลา ไม่ใช่ต้องชี้เมาส์ถาม — ป้ายด้านบนจึงเป็นทั้งตัวนับและคำอธิบายสี
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

# ชนิดจุด → (ชื่อที่คนอ่าน, สิ่งที่ต้องทำกับมัน) เรียงตามความด่วน
# ข้อความคอลัมน์ที่สองคือหัวใจ: บอกว่าเห็นสีนี้แล้วต้องทำอะไร ไม่ใช่แค่ว่ามันคืออะไร
_KIND = {
    "mixed": ("ผิดแน่", "แก้ได้เลย"),
    "shaky": ("ไม่นิ่ง", "อ่าน ๓ รอบไม่ตรงกัน"),
    "digit": ("ตัวเลข", "เทียบกับภาพ"),
}
_ARABIC_TO_THAI = str.maketrans("0123456789", THAI_DIGITS)

CSS = """
<style>
/* ── ภาพหน้าเอกสาร + กรอบชี้จุด ─────────────────────────────── */
.rv-stick{position:sticky;top:.6rem}
.stu-wrap{position:relative;line-height:0}
.stu-wrap img{width:100%;border-radius:var(--radius-sm);display:block;
  border:1px solid var(--border)}
.stu-wrap svg{position:absolute;inset:0;width:100%;height:100%}
.stu-box{fill:none;stroke-width:6}
.stu-box.k-digit{stroke:var(--rv-digit)}
.stu-box.k-mixed{stroke:var(--rv-mixed)}
.stu-box.k-shaky{stroke:var(--rv-shaky)}
.stu-hit.k-digit{fill:var(--rv-digit);opacity:.07}
.stu-hit.k-mixed{fill:var(--rv-mixed);opacity:.10}
.stu-hit.k-shaky{fill:var(--rv-shaky);opacity:.10}
/* ขอบขาวรอบตัวเลขกำกับ — ไม่งั้นเลขจมไปกับตัวหนังสือในภาพเอกสารเวลาย่อ
   สีต้องมาจากคลาส ไม่ใช่ attribute fill="var(...)" — เบราว์เซอร์ไม่ขยายตัวแปร
   CSS ใน presentation attribute ของ SVG เลขจะกลายเป็นสีดำหมด */
.stu-no{font-family:var(--mono);font-size:42px;font-weight:700;
  stroke:#fff;stroke-width:6px;paint-order:stroke fill}
.stu-no.k-digit{fill:var(--rv-digit)}
.stu-no.k-mixed{fill:var(--rv-mixed)}
.stu-no.k-shaky{fill:var(--rv-shaky)}

/* ── แถบสรุปด้านบน — ตัวนับกับคำอธิบายสีเป็นอันเดียวกัน ─────── */
.rv-head{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
  border:1px solid var(--border);border-radius:var(--radius);
  padding:.7rem .95rem;background:var(--paper)}
.rv-score{display:flex;align-items:baseline;gap:.5rem;padding-right:1rem;
  border-right:1px solid var(--border)}
.rv-big{font-family:var(--mono);font-size:29px;font-weight:700;line-height:1;
  color:var(--ink)}
.rv-cap{font-size:11.5px;line-height:1.5;color:var(--ink-soft)}
.rv-cap b{display:block;font-weight:500;opacity:.75}
.rv-keys{display:flex;gap:.4rem;flex-wrap:wrap}
.rv-key{display:inline-flex;align-items:baseline;gap:.4rem;
  padding:.32rem .7rem;border-radius:999px}
.rv-key .n{font-family:var(--mono);font-size:14px;font-weight:700}
.rv-key .l{font-size:12.5px;font-weight:600}
.rv-key .w{font-size:11px;opacity:.72}
.rv-key.k-digit{background:var(--rv-digit-bg);color:var(--rv-digit)}
.rv-key.k-mixed{background:var(--rv-mixed-bg);color:var(--rv-mixed)}
.rv-key.k-shaky{background:var(--rv-shaky-bg);color:var(--rv-shaky)}
.rv-key.off{background:var(--surface-2);color:var(--ink-soft)}

/* แผนที่บรรทัด — ขีดละบรรทัดเรียงตามหน้าจริง บอกว่าปัญหากระจุกอยู่ช่วงไหน
   ตัวเลขรวมด้านบนบอกไม่ได้ว่า "๘ จุด" กองอยู่ย่อหน้าเดียวหรือกระจายทั้งหน้า */
.rv-map{display:flex;gap:2px;height:13px;margin:.5rem .1rem 0;overflow:hidden}
.rv-map i{flex:1;min-width:1px;border-radius:2px;background:var(--surface-2)}
.rv-map i.k-digit{background:var(--rv-digit)}
.rv-map i.k-mixed{background:var(--rv-mixed)}
.rv-map i.k-shaky{background:var(--rv-shaky)}

/* ── ป้ายบอกที่มาของภาพ/พิกัด ──────────────────────────────── */
.rv-meta{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.45rem}
.rv-chip{font-size:11.5px;line-height:1.6;padding:.15rem .55rem;border-radius:999px;
  background:var(--surface-2);color:var(--ink-soft);border:1px solid var(--border)}
.rv-chip.mono{font-family:var(--mono);font-size:11px}
.rv-chip.warn{background:var(--warn-bg);color:var(--warn-ink);border-color:#F0DCBA}
.rv-chip.good{background:var(--good-bg);color:var(--good-ink);border-color:#C6E8D3}

/* ── กล่องข้อความ ─────────────────────────────────────────────
   กล่องนี้เป็นแถวของ Streamlit ไม่ใช่ HTML ก้อนเดียวเหมือนก่อน เพราะเลขบรรทัด
   ต้องเป็นปุ่มจริง (ฝังปุ่มใน markdown ไม่ได้) แลกมาด้วยการต้องรีดช่องไฟ
   ที่ Streamlit ใส่ให้ทุกบล็อกออก ไม่งั้นข้อความไม่ต่อเนื่องเป็นเอกสาร */
.st-key-rvdoc{padding:.7rem .8rem .7rem .3rem;background:var(--paper)}
.st-key-rvdoc [data-testid="stVerticalBlock"]{gap:0}
.st-key-rvdoc [data-testid="stElementContainer"]{margin:0}
/* popup ภาพต้องล้นออกนอกคอลัมน์ได้ */
.st-key-rvdoc [data-testid="stColumn"]{overflow:visible}
.st-key-rvdoc [data-testid="stHorizontalBlock"]{align-items:flex-start}

/* เลขบรรทัดคือปุ่ม แต่ต้องดูเป็นเลข ไม่ใช่ปุ่ม จนกว่าจะเอาเมาส์ไปชี้
   เจาะจงที่ tertiary เท่านั้น ปุ่มบันทึก/ยกเลิกในกล่องเดียวกันจะได้ไม่โดนกลืน */
.st-key-rvdoc [data-testid="stBaseButton-tertiary"]{font-family:var(--mono);
  font-size:11px;font-weight:400;color:var(--ink-soft);opacity:.5;
  padding:.25rem 0 0;min-height:0;border:none;background:transparent;
  justify-content:flex-end}
.st-key-rvdoc [data-testid="stBaseButton-tertiary"]:hover{opacity:1;
  color:var(--accent);background:transparent;text-decoration:underline}
.st-key-rvdoc [data-testid="stBaseButton-tertiary"]:focus-visible{opacity:1;
  color:var(--accent)}
.rv-live-no{font-family:var(--mono);font-size:11px;font-weight:700;
  color:var(--accent);text-align:right;padding-top:.6rem}

.stu-row{display:flex;gap:.6rem;align-items:baseline;position:relative;
  padding:.2rem .5rem .2rem .45rem;border-left:3px solid transparent}
.stu-row.hit.k-digit{border-left-color:var(--rv-digit);background:var(--rv-digit-bg)}
.stu-row.hit.k-mixed{border-left-color:var(--rv-mixed);background:var(--rv-mixed-bg)}
.stu-row.hit.k-shaky{border-left-color:var(--rv-shaky);background:var(--rv-shaky-bg)}
/* บรรทัดที่ถูก mark ใช้เส้นขอบตอนชี้ ไม่ใช่พื้นหลัง — พื้นหลังจะทับสีชนิดจุด */
.stu-row:hover{box-shadow:inset 0 0 0 1px var(--border);border-radius:0 .3rem .3rem 0}
.stu-row:not(.hit):hover{background:var(--surface-2)}
/* ช่องว่างตรงที่ตัวกรองซ่อนบรรทัดไว้ — ไม่งั้นเลขบรรทัดกระโดดโดยไม่มีสัญญาณ
   แล้วคนจะนึกว่าเอกสารขาดหายไปจริง ๆ */
.stu-gap{display:flex;align-items:center;gap:.55rem;user-select:none;
  padding:.25rem .5rem .25rem 3.4rem;font-size:10.5px;color:var(--ink-soft);opacity:.6}
.stu-gap::after{content:"";flex:1;height:1px;background:var(--border)}
.stu-txt{font-size:15.5px;line-height:1.95;word-break:break-word;flex:1}
.num{background:var(--rv-digit-bg);color:#3730A3;border-radius:4px;
  padding:0 .12em;font-weight:600;position:relative;cursor:help}
/* ระบายพื้นทั้งบรรทัดเฉพาะตอนที่ "ไม่นิ่ง" เป็นชนิดหลักของบรรทัดนั้น
   บรรทัดที่เป็นทั้งผิดแน่และไม่นิ่งจะได้ไม่มีเหลืองซ้อนแดงจนอ่านสีไม่ออก
   ข้อมูลไม่หาย — ป้ายใต้ภาพ hover บอกครบทุกชนิดที่บรรทัดนั้นโดน */
.stu-row.k-shaky .shaky-line{background:rgba(180,83,9,.11);
  border-radius:4px;padding:.05em .15em}

/* ทูลทิปในกล่องนี้เปิดลงล่างเสมอ เพราะด้านบนของบรรทัดถูกภาพ hover จองไว้แล้ว
   (ของกลางใน theme.py เปิดขึ้นบน จึงต้องกลับด้านเฉพาะที่นี่) */
.num::after{content:attr(data-tip);position:absolute;left:50%;top:calc(100% + 7px);
  transform:translateX(-50%);background:var(--ink);color:#F5F6F8;font-size:12px;
  font-weight:500;line-height:1.5;padding:.35rem .6rem;border-radius:8px;
  white-space:normal;max-width:250px;width:max-content;opacity:0;visibility:hidden;
  pointer-events:none;transition:opacity .12s ease;z-index:70}
.num:hover::after{opacity:1;visibility:visible}
.stu-row .wrong::after{bottom:auto;top:calc(100% + 7px)}
.stu-row .wrong::before{bottom:auto;top:100%;
  border-top-color:transparent;border-bottom-color:var(--ink)}

/* ── ภาพครอปเด้งเหนือบรรทัดที่ชี้ ไม่ใช่ตำแหน่งคงที่บนกล่อง ──
   เคยลองวางไว้บนสุดของกล่องแล้ว แต่พอชี้บรรทัดล่าง ๆ ภาพจะอยู่นอกจอที่มองเห็น
   กล่องจึงต้องไม่มี overflow ของตัวเอง ไม่งั้นภาพเหนือบรรทัดแรก ๆ ถูกตัดหัวทิ้ง
   ใช้ CSS ล้วน ไม่ง้อ JS เพราะ Streamlit ตัด script ที่ฝังมากับ markdown ทิ้ง */
.stu-peek{display:none;position:absolute;left:.45rem;bottom:calc(100% + 9px);
  z-index:60;width:min(620px,calc(100% - .6rem));padding:.4rem;
  background:var(--paper);border:1px solid var(--border);
  border-radius:var(--radius-sm);box-shadow:0 12px 34px rgba(20,22,27,.20)}
.stu-peek::after{content:"";position:absolute;left:1.5rem;top:100%;
  border:7px solid transparent;border-top-color:var(--border)}
/* สองบรรทัดแรกไม่มีที่ว่างข้างบน พลิกลงล่างแทน ลูกศรพลิกตาม
   คลาส .dn ติดมาจากฝั่ง Python ไม่ใช่ :nth-child เพราะมีตัวคั่น .stu-gap
   แทรกอยู่ในกล่องด้วย การนับลูกตามลำดับจึงชี้ผิดตัวเมื่อเปิดตัวกรอง */
.stu-row.dn>.stu-peek{bottom:auto;top:calc(100% + 9px)}
.stu-row.dn>.stu-peek::after{top:auto;bottom:100%;
  border-top-color:transparent;border-bottom-color:var(--border)}
.stu-peek img{display:block;width:100%;border-radius:.3rem}
.stu-peek .cap{display:flex;gap:.4rem;align-items:center;font-size:11px;
  color:var(--ink-soft);padding:.35rem .15rem 0}
.stu-peek .cap b{font-family:var(--mono);font-weight:700;color:var(--ink)}
.stu-row:hover>.stu-peek{display:block}

/* ── รายการที่ระบบเดาคำตอบให้ได้เอง ────────────────────────── */
.rv-fix{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;
  border:1px solid #C6E8D3;background:var(--good-bg);border-radius:var(--radius-sm);
  padding:.5rem .7rem;margin-top:.55rem}
.rv-fix .h{font-size:12px;font-weight:700;color:var(--good-ink);margin-right:.2rem}
.rv-fix .i{display:inline-flex;gap:.35rem;align-items:baseline;font-size:12.5px;
  background:var(--paper);border-radius:999px;padding:.15rem .6rem;color:var(--ink)}
.rv-fix .i b{font-family:var(--mono);font-size:11px;color:var(--good-ink)}
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


def row_kind(row: review.ReviewLine) -> str | None:
    """สีเดียวต่อบรรทัด เอาชนิดที่ด่วนที่สุด — ผิดแน่ > ไม่นิ่ง > ตัวเลข

    บรรทัดหนึ่งมีได้หลายชนิด แต่ถ้าระบายหลายสีในบรรทัดเดียว คนจะอ่านสีไม่ออก
    จึงเลือกสีตามสิ่งที่ต้องทำก่อน แล้วรายละเอียดที่เหลืออยู่ในไฮไลต์ระดับคำ
    """
    for kind in _KIND:
        if any(m.kind == kind for m in row.marks):
            return kind
    return None


def _overlay(uri: str, w: int, h: int, rows: list) -> str:
    """วาดกรอบทับภาพตรงบรรทัดที่ต้องตรวจ พร้อมเลขกำกับให้ตรงกับฝั่งข้อความ

    ใช้ SVG ซ้อนบนภาพแทนการวาดลงไฟล์ เพราะไม่ต้องสร้างภาพใหม่ทุกครั้ง
    และกรอบยังคมชัดเมื่อผู้ใช้ซูมหน้าเว็บ

    viewBox ใช้ขนาดภาพจริง จะได้ใส่พิกัดดิบจาก engine ลงไปตรง ๆ
    ไม่ต้องแปลงสเกลเอง ซึ่งเป็นจุดที่พลาดง่ายเวลาภาพถูกย่อให้พอดีคอลัมน์
    """
    shapes = []
    for r in rows:
        if not r.box or not r.needs_check:
            continue
        x, y, bw, bh = r.box
        kind = row_kind(r) or "digit"
        shapes.append(
            f'<rect class="stu-hit k-{kind}" x="{x}" y="{y}" width="{bw}" height="{bh}"/>'
            f'<rect class="stu-box k-{kind}" x="{x}" y="{y}" width="{bw}" height="{bh}"'
            f' rx="8"/>'
            f'<text class="stu-no k-{kind}" x="{max(x - 14, 8)}" y="{y + bh - 8}"'
            f' text-anchor="end">{r.index + 1}</text>'
        )
    return (
        f'<div class="rv-stick"><div class="stu-wrap">'
        f'<img src="{uri}" alt="หน้าเอกสาร">'
        f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'{"".join(shapes)}</svg></div></div>'
    )


def _inline(row: review.ReviewLine) -> str:
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
        body.append(
            f'<span class="{cls}" data-tip="{html.escape(tip)}">'
            f"{html.escape(row.text[m.start : m.end])}</span>"
        )
        cursor = m.end
    body.append(html.escape(row.text[cursor:]))

    inner = "".join(body)
    if any(m.kind == "shaky" for m in row.marks):
        inner = f'<span class="shaky-line">{inner}</span>'
    return inner


def _header(s: dict, rows: list, measured: bool) -> str:
    """แถบสรุป — ตัวนับแต่ละสีพร้อมคำว่าเห็นสีนั้นแล้วต้องทำอะไร

    ของเดิมเป็นป้ายตัวเลขล้วน ("ตัวเลข ๑๒") ซึ่งบอกไม่ได้ว่าสีนั้นแปลว่าอะไร
    คนต้องชี้เมาส์ถามทีละจุดถึงจะรู้ ทั้งที่คำอธิบายควรอยู่ให้อ่านได้ตลอด
    """
    keys = []
    for kind, (label, what) in _KIND.items():
        n = s[{"digit": "digits", "mixed": "mixed", "shaky": "shaky"}[kind]]
        if kind == "shaky" and not measured:
            keys.append(
                '<span class="rv-key off"><span class="n">—</span>'
                '<span class="l">ไม่นิ่ง</span>'
                '<span class="w">ยังไม่ได้วัด ไปแท็บ 🎯</span></span>'
            )
            continue
        off = "" if n else " off"
        keys.append(
            f'<span class="rv-key k-{kind}{off}"><span class="n">{n}</span>'
            f'<span class="l">{label}</span><span class="w">{what}</span></span>'
        )

    ticks = "".join(
        f'<i class="k-{k}"></i>' if (k := row_kind(r)) else "<i></i>" for r in rows
    )
    return (
        f'<div class="rv-head"><div class="rv-score">'
        f'<span class="rv-big">{s["to_check"]}</span>'
        f'<span class="rv-cap">บรรทัดต้องตรวจ<b>จาก {s["lines"]} บรรทัด</b></span>'
        f'</div><div class="rv-keys">{"".join(keys)}</div></div>'
        f'<div class="rv-map" title="ขีดละบรรทัด เรียงตามลำดับในหน้า">{ticks}</div>'
    )


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

    st.markdown(_header(s, rows, shaky is not None), unsafe_allow_html=True)

    img_dir = CLEAN_IMAGE_DIR if engine.endswith("+clean") else IMAGE_DIR
    img = img_dir / f"{picked.page_id}.png"

    left, right = st.columns([1, 1.05])
    with left:
        st.markdown(_image_meta(donor, s), unsafe_allow_html=True)
        if img.exists():
            uri, w, h = cached_image(img)
            st.markdown(_overlay(uri, w, h, rows), unsafe_allow_html=True)
        else:
            st.warning(f"ไม่พบภาพใน {img_dir.name}/")

    with right:
        _text_panel(picked, engine, rows, lines, saved, img)


def _image_meta(donor: str | None, s: dict) -> str:
    """ป้ายสั้น ๆ บอกที่มาของภาพและพิกัด แทนคำบรรยายยาวแบบบรรทัด log

    เรื่องพิกัดยืมมาสำคัญพอที่จะต้องเห็นทุกครั้ง เพราะบรรทัดที่ยืมไม่ได้
    จะไม่มีกรอบบนภาพ ซึ่งดูเผิน ๆ เหมือนบรรทัดนั้นไม่มีปัญหา
    """
    chips = ['<span class="rv-chip">ภาพที่ engine อ่านจริง</span>']
    if donor is None:
        chips.append('<span class="rv-chip warn">ไม่มี engine ไหนคืนพิกัด วาดกรอบไม่ได้</span>')
    else:
        full = s["with_box"] >= s["lines"]
        chips.append(f'<span class="rv-chip mono">พิกัดยืมจาก {html.escape(donor)}</span>')
        chips.append(
            f'<span class="rv-chip {"good" if full else "warn"}">'
            f'ชี้จุดได้ {s["with_box"]}/{s["lines"]} บรรทัด</span>'
        )
    return f'<div class="rv-meta">{"".join(chips)}</div>'


def _slot(picked, engine: str) -> str:
    """คีย์บอกว่าตอนนี้กำลังแก้บรรทัดของหน้าไหน/engine ไหนอยู่

    ต้องผูกกับหน้าและ engine ไม่ใช่เก็บแค่เลขบรรทัด ไม่งั้นเปิดแก้บรรทัด ๗
    แล้วกดข้ามหน้า หน้าใหม่จะเปิดช่องแก้บรรทัด ๗ ค้างไว้เองทั้งที่ไม่ได้สั่ง
    """
    return f"{picked.page_id}|{engine}"


def _editing_at(picked, engine: str) -> int | None:
    at = st.session_state.get("rv_ln")
    return at[1] if at and at[0] == _slot(picked, engine) else None


def _close_edit(picked, engine: str, index: int) -> None:
    """ปิดช่องแก้ พร้อมทิ้งค่าที่พิมพ์ค้างไว้ใน widget

    ถ้าไม่ทิ้ง พอเปิดบรรทัดเดิมอีกครั้ง Streamlit จะคืนค่าที่เคยพิมพ์
    แทนค่าที่บันทึกไปแล้ว ซึ่งดูเหมือนบันทึกไม่ติด
    """
    st.session_state.pop("rv_ln", None)
    st.session_state.pop(f"rvtxt|{_slot(picked, engine)}|{index}", None)


def _read_row(r: review.ReviewLine, seat: int, img, mtime: float, slot: str) -> bool:
    """บรรทัดโหมดอ่าน — เลขบรรทัดคือปุ่ม กดแล้วแก้ตรงนั้น คืน True ถ้าถูกกด

    ทำไมต้องเป็นแถวของ Streamlit ไม่ใช่ HTML ก้อนเดียวเหมือนก่อน:
    ปุ่มจริงฝังใน markdown ไม่ได้ และถ้าไม่มีปุ่มต่อบรรทัด คนก็ต้องเลื่อนลง
    ไปหาช่องพิมพ์ที่ก้นหน้า ซึ่งไกลจากจุดที่กำลังดูอยู่
    """
    c = st.columns([0.62, 9.38], gap="small", vertical_alignment="top")
    hit = c[0].button(
        str(r.index + 1),
        key=f"rvln|{slot}|{r.index}",
        type="tertiary",
        help="กดเพื่อแก้บรรทัดนี้",
        width="stretch",
    )

    kind = row_kind(r)
    cls = f"stu-row hit k-{kind}" if kind else "stu-row"
    if seat < 2:
        cls += " dn"  # สองบรรทัดบนสุดไม่มีที่ให้ภาพลอยขึ้นข้างบน
    # ทำภาพให้ทุกบรรทัดที่มีพิกัด ไม่ใช่เฉพาะที่ mark — คนตรวจอาจสงสัย
    # บรรทัดที่ระบบไม่ได้ชี้ก็ได้ วัดแล้วหน้าที่ใหญ่สุดโตจาก 108 เป็น 162 KB
    peek = peek_uri(str(img), tuple(r.box), mtime) if r.box and img.exists() else None
    # ป้ายบอกครบทุกชนิด ไม่ใช่เฉพาะชนิดหลักที่ใช้เลือกสี
    got = [lb for k, (lb, _) in _KIND.items() if any(m.kind == k for m in r.marks)]
    why = " · " + " · ".join(got) if got else ""
    shot = (
        f'<span class="stu-peek"><img src="{peek}" alt="ภาพบรรทัดนี้">'
        f'<span class="cap"><b>บรรทัด {r.index + 1}</b>ภาพจริงจากหน้าเอกสาร{why}'
        f"</span></span>"
        if peek else ""
    )
    c[1].markdown(
        f'<div class="{cls}">{shot}<span class="stu-txt">{_inline(r)}</span></div>',
        unsafe_allow_html=True,
    )
    return hit


def _edit_row(r: review.ReviewLine, picked, engine: str, lines: list[str]) -> None:
    """ช่องพิมพ์แทนที่บรรทัดนั้นตรงตำแหน่งเดิม บรรทัดอื่นยังอ่านได้ปกติ

    เดิมช่องพิมพ์เป็นก้อนเดียวทั้งหน้าอยู่ก้นหน้า พอจะแก้บรรทัดที่ ๖ ต้องเลื่อน
    ลงไปไกลจากไฮไลต์ที่กำลังดู แล้วเลื่อนกลับขึ้นมาเทียบ — เสียจังหวะทุกครั้ง
    """
    slot = _slot(picked, engine)
    c = st.columns([0.62, 7.1, 2.28], gap="small", vertical_alignment="top")
    c[0].markdown(f'<div class="rv-live-no">{r.index + 1}</div>', unsafe_allow_html=True)
    text = c[1].text_input(
        f"แก้บรรทัด {r.index + 1}",
        value=r.text,
        key=f"rvtxt|{slot}|{r.index}",
        label_visibility="collapsed",
    )
    act = c[2].columns(2, gap="small")
    if act[0].button(
        "บันทึก", type="primary", key=f"rvok|{slot}|{r.index}", width="stretch"
    ):
        new = list(lines)
        new[r.index] = text.strip()
        markdown_out.save_page(picked.page_id, engine, "\n".join(new))
        st.session_state["rv_just_saved"] = picked.page_id
        _close_edit(picked, engine, r.index)
        st.rerun()
    if act[1].button("ยกเลิก", key=f"rvno|{slot}|{r.index}", width="stretch"):
        _close_edit(picked, engine, r.index)
        st.rerun()


def _text_panel(picked, engine, rows, lines, saved, img) -> None:
    """ฝั่งข้อความ — เอกสารต่อเนื่องที่กดแก้ได้ทีละบรรทัดตรงตำแหน่ง

    ของเดิมวาดป้าย "บรรทัด N · ตัวเลข" กับคำอธิบายคั่นทุกบรรทัดที่ mark
    ผลคือข้อความถูกหั่นเป็นชิ้น อ่านเป็นเอกสารไม่ได้ ทั้งที่คนตรวจต้อง
    อ่านความต่อเนื่องเพื่อรู้ว่าคำไหนควรเป็นอะไร

    ตอนนี้เลขบรรทัดริมซ้ายเป็นปุ่ม กดแล้วบรรทัดนั้นกลายเป็นช่องพิมพ์ตรงที่เดิม
    ไม่ต้องเลื่อนไปหาช่องแก้ที่อื่น บรรทัดที่เหลือยังระบายสีให้เทียบได้ตลอด
    """
    at = _editing_at(picked, engine)
    bar = st.columns([1.9, 2.2])
    only = bar[0].toggle(
        "เฉพาะที่ต้องตรวจ",
        value=True,
        key="rv_only",
        disabled=at is not None,
        help="ปิดเองตอนกำลังแก้บรรทัด เพื่อไม่ให้บรรทัดที่แก้อยู่หายไปกลางคัน",
    )
    if at is not None:
        only = False

    # st.success ที่วางไว้ก่อน st.rerun ไม่เคยถูกวาด — เก็บสถานะข้ามรอบมาแทน
    if st.session_state.pop("rv_just_saved", None) == picked.page_id:
        bar[1].markdown(
            '<div class="rv-meta" style="margin-top:.55rem">'
            '<span class="rv-chip good">บันทึกแล้ว</span></div>',
            unsafe_allow_html=True,
        )
    elif saved is not None:
        bar[1].markdown(
            f'<div class="rv-meta" style="margin-top:.55rem">'
            f'<span class="rv-chip">กำลังดูฉบับที่แก้ไว้ · {len(lines)} บรรทัด</span></div>',
            unsafe_allow_html=True,
        )

    shown = [r for r in rows if r.needs_check or not only]
    if not shown:
        st.success("ไม่มีบรรทัดไหนต้องตรวจ — ไม่ได้แปลว่าอ่านถูกหมด")
        return

    mtime = img.stat().st_mtime if img.exists() else 0.0
    slot = _slot(picked, engine)
    with st.container(border=True, key="rvdoc", gap="xxsmall"):
        prev = None
        for seat, r in enumerate(shown):
            if prev is not None and r.index > prev + 1:
                st.markdown(
                    f'<div class="stu-gap">ข้าม {r.index - prev - 1} '
                    f"บรรทัดที่ไม่มีจุดต้องตรวจ</div>",
                    unsafe_allow_html=True,
                )
            prev = r.index
            if r.index == at:
                _edit_row(r, picked, engine, lines)
            elif _read_row(r, seat, img, mtime, slot):
                st.session_state["rv_ln"] = (slot, r.index)
                st.rerun()

    st.caption("ชี้เมาส์ที่บรรทัดไหนก็ได้เพื่อดูภาพจริง · กดเลขบรรทัดเพื่อแก้ตรงนั้น")

    # คำแนะนำรวมไว้ที่เดียวใต้กล่อง ไม่แทรกคั่นกลางข้อความ
    fixes = [
        (r.index + 1, f)
        for r in shown
        for m in r.marks
        if (f := suggest(m, r.text))
    ]
    if fixes:
        items = "".join(
            f'<span class="i"><b>{n}</b>{html.escape(f)}</span>' for n, f in fixes[:8]
        )
        more = f'<span class="i">+{len(fixes) - 8}</span>' if len(fixes) > 8 else ""
        st.markdown(
            f'<div class="rv-fix"><span class="h">แก้ได้เลยไม่ต้องดูภาพ</span>'
            f"{items}{more}</div>",
            unsafe_allow_html=True,
        )

    _whole_page(picked, engine, lines, saved)


def _whole_page(picked, engine, lines: list[str], saved: str | None) -> None:
    """ช่องพิมพ์ทั้งหน้า เก็บพับไว้ ไม่ใช่ทางหลักอีกแล้ว

    ยังต้องมีอยู่เพราะช่องรายบรรทัดย้ายข้อความข้ามบรรทัดไม่ได้ ซึ่งจำเป็นเวลา
    OCR หั่นบรรทัดผิดที่ — เคสที่เจอบ่อยกับ engine ที่ตีกรอบพลาด
    แต่เป็นงานที่นาน ๆ ทำที จึงไม่ควรกินที่เหนือกว่าการแก้ทีละบรรทัด
    """
    with st.expander("แก้ทั้งหน้าในช่องเดียว — ใช้ตอนต้องย้ายข้อความข้ามบรรทัด"):
        text = st.text_area(
            "ข้อความทั้งหน้า",
            value="\n".join(lines),
            height=420,
            key=f"rv_area|{picked.page_id}|{engine}",
            label_visibility="collapsed",
        )
        new = [ln.strip() for ln in text.splitlines() if ln.strip()]
        changed = new != lines

        b = st.columns([1.5, 1.3, 2])
        if b[0].button(
            "บันทึกทั้งหน้า", type="primary", disabled=not changed,
            key=f"rv_save|{picked.page_id}",
        ):
            markdown_out.save_page(picked.page_id, engine, "\n".join(new))
            st.session_state["rv_just_saved"] = picked.page_id
            st.rerun()

        if saved is not None and b[1].button(
            "ล้างที่แก้ไว้", key=f"rv_reset|{picked.page_id}"
        ):
            markdown_out.clear_page(picked.page_id, engine)
            st.rerun()

        b[2].caption(
            f"{len(new)} บรรทัด · "
            + ("มีการแก้ ยังไม่บันทึก" if changed else "ยังไม่ได้แก้อะไร")
        )
