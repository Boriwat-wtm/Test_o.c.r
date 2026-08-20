"""หน้าเปรียบเทียบแบบ split view — สร้างเป็น HTML component ตัวเดียว

ทำไมไม่ใช้ widget ของ Streamlit ตรง ๆ
    สี่อย่างที่ต้องการทำด้วย Streamlit ล้วน ๆ ไม่ได้
      1. ซูม/ลาก/หมุนรูป            ต้องมี JS จับ event เอง
      2. scroll แยกฝั่งซ้าย-ขวา      Streamlit มี scroll container เดียวทั้งหน้า
      3. hover ข้อความ -> ไฮไลต์กรอบบนรูป   ต้องสื่อสารสองทางในเฟรมเดียวกัน
      4. สลับโหมดเดี่ยว/เทียบ        ถ้าใช้ st.rerun จะรีเซ็ตตำแหน่ง scroll ทุกครั้ง
    จึงรวมทุกอย่างเป็น HTML ก้อนเดียวแล้วให้ Streamlit ส่งข้อมูลเข้าไปทาง JSON
    ฝั่ง Python ทำหน้าที่แค่คำนวณผลกับเตรียมข้อมูล ไม่ยุ่งกับการแสดงผล

ข้อจำกัดที่ต้องรองรับ
    typhoon-api ไม่มี bounding box (API คืนแต่ข้อความ ไม่มีพิกัด)
    บรรทัดของมันจึงชี้ตำแหน่งบนรูปไม่ได้ ต้องบอกผู้ใช้ให้ชัด ไม่ใช่เงียบไป
"""

from __future__ import annotations

import base64
import html
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

# ย่อรูปก่อนฝังเป็น base64 — ต้นฉบับ 300 DPI ราว 2481x3508 ถ้าฝังทั้งดุ้น
# จะได้ base64 หลายเมกะไบต์ต่อการ render หนึ่งครั้ง หน้าเว็บจะอืด
# ผู้ใช้ซูมได้อยู่แล้ว ความละเอียดระดับนี้พอสำหรับอ่านเทียบ
VIEWER_MAX_WIDTH = 1400


@dataclass
class LineRecord:
    """หนึ่งบรรทัดในฝั่งผลลัพธ์"""

    kind: str  # matched | missed | spurious
    html: str  # ข้อความพร้อมไฮไลต์ diff (ผ่าน escape มาแล้ว)
    box: list[int] | None = None  # [x, y, w, h] ในพิกัดรูปต้นฉบับ
    conf: float | None = None


@dataclass
class EngineRecord:
    name: str
    badges: list[dict] = field(default_factory=list)  # {label, tone}
    notes: list[dict] = field(default_factory=list)  # {kind, text}
    lines: list[LineRecord] = field(default_factory=list)
    has_boxes: bool = True
    # ตระกูล engine ใช้จัดกลุ่มในฝั่งผลลัพธ์ ตัวเดียวกันที่รันคนละภาพต้นทาง
    # อยู่กลุ่มเดียวกัน จะได้เทียบ "ลบลายน้ำแล้วดีขึ้นไหม" ได้โดยไม่ต้องสลับแท็บ
    group: str = ""
    variant: str = ""  # ป้ายบนการ์ดในกลุ่ม เช่น ภาพดิบ / ลบลายน้ำ


def encode_image(path: Path, max_width: int = VIEWER_MAX_WIDTH) -> tuple[str, int, int]:
    """ย่อรูปแล้วแปลงเป็น data URI

    คืน (data_uri, ความกว้างต้นฉบับ, ความสูงต้นฉบับ)
    ต้องคืนขนาดต้นฉบับด้วยเพราะ bounding box เก็บเป็นพิกัดของรูปต้นฉบับ
    ฝั่ง JS ต้องรู้อัตราส่วนเพื่อวาดกรอบให้ตรงตำแหน่ง
    """
    with Image.open(path) as im:
        original_w, original_h = im.size
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, round(im.height * ratio)), Image.LANCZOS)
        buffer = io.BytesIO()
        im.convert("L").save(buffer, format="WEBP", quality=82, method=4)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}", original_w, original_h


def build_html(
    *,
    image_uri: str,
    image_w: int,
    image_h: int,
    page_title: str,
    truth_lines: list[str],
    engines: list[EngineRecord],
    height: int,
) -> str:
    payload = {
        "image": image_uri,
        "imgW": image_w,
        "imgH": image_h,
        "pageTitle": page_title,
        "truth": [html.escape(t) for t in truth_lines],
        "engines": [
            {
                "name": e.name,
                "group": e.group or e.name,
                "variant": e.variant,
                "badges": e.badges,
                "notes": e.notes,
                "hasBoxes": e.has_boxes,
                "lines": [
                    {"kind": ln.kind, "html": ln.html, "box": ln.box, "conf": ln.conf}
                    for ln in e.lines
                ],
            }
            for e in engines
        ],
    }
    # กัน payload ปิด <script> ก่อนเวลาอันควร
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data).replace("__HEIGHT__", str(height))


_TEMPLATE = r"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');
  * { box-sizing: border-box; }
  :root {
    --ink:#14161B; --ink-soft:#5B5F6B; --ink-faint:#8A8F9C;
    --surface:#FFFFFF; --surface-2:#F5F6F8; --border:#E4E6EC;
    --accent:#4F46E5; --accent-soft:#EEF0FF;
    --good-bg:#E6F6EC; --good-ink:#0E7A46;
    --warn-bg:#FDF1DF; --warn-ink:#93630A;
    --bad-bg:#FCE7EA;  --bad-ink:#B0123B;
    --mono:"JetBrains Mono",ui-monospace,Consolas,monospace;
  }
  #root {
    font-family:"IBM Plex Sans Thai","Noto Sans Thai","Leelawadee UI","Segoe UI",sans-serif;
    color:var(--ink); height:__HEIGHT__px; display:flex; flex-direction:column;
    border:1px solid var(--border); border-radius:14px; overflow:hidden;
    background:var(--surface);
  }

  /* ── แถบควบคุมด้านบน ── */
  .bar { display:flex; align-items:center; gap:.6rem; padding:.55rem .8rem;
         border-bottom:1px solid var(--border); background:var(--surface-2); flex:none;
         flex-wrap:wrap; }
  .bar .title { font-size:13px; font-weight:600; margin-right:auto;
                white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .seg { display:inline-flex; background:var(--surface); border:1px solid var(--border);
         border-radius:8px; overflow:hidden; }
  .seg button { border:0; background:transparent; padding:.34rem .8rem; font-size:12.5px;
                font-weight:600; cursor:pointer; color:var(--ink-soft);
                font-family:inherit; }
  .seg button.on { background:var(--accent); color:#fff; }
  .btn { border:1px solid var(--border); background:var(--surface); border-radius:8px;
         padding:.34rem .6rem; font-size:12.5px; cursor:pointer; color:var(--ink);
         font-family:inherit; font-weight:500; }
  .btn:hover { background:var(--surface-2); }

  /* ── โครง split ── */
  .split { flex:1; display:flex; min-height:0; }
  .pane-l { width:42%; min-width:260px; border-right:1px solid var(--border);
            display:flex; flex-direction:column; background:var(--surface-2); }
  .pane-r { flex:1; min-width:0; display:flex; flex-direction:column; }

  /* ── ตัวดูรูป ── */
  .imgtools { display:flex; align-items:center; gap:.3rem; padding:.4rem .6rem;
              border-bottom:1px solid var(--border); background:var(--surface); flex:none; }
  .imgtools .zoomval { font-family:var(--mono); font-size:11.5px; color:var(--ink-soft);
                       min-width:44px; text-align:center; }
  .imgtools .spacer { margin-left:auto; font-size:11.5px; color:var(--ink-faint); }
  .stage { flex:1; overflow:hidden; position:relative; cursor:grab;
           background:#DFE2E8; }
  .stage.drag { cursor:grabbing; }
  .canvas { position:absolute; transform-origin:0 0; }
  .canvas img { display:block; }
  .boxes { position:absolute; inset:0; pointer-events:none; }
  .bx { position:absolute; border:2px solid var(--accent);
        background:rgba(79,70,229,.14); border-radius:2px; display:none; }
  .bx.on { display:block; }

  /* ── ฝั่งผลลัพธ์ ── */
  .tabs { display:flex; gap:.25rem; padding:.45rem .6rem 0; border-bottom:1px solid var(--border);
          overflow-x:auto; flex:none; background:var(--surface); }
  .tabs button { border:0; border-bottom:2px solid transparent; background:transparent;
                 padding:.4rem .7rem .5rem; font-size:12.5px; font-weight:600; cursor:pointer;
                 color:var(--ink-soft); white-space:nowrap; font-family:var(--mono); }
  .tabs button.on { color:var(--accent); border-bottom-color:var(--accent); }
  .scroll { flex:1; overflow-y:auto; padding:.75rem .85rem 1.5rem; }
  /* โหมดเทียบพร้อมกัน: ตั้งความกว้างขั้นต่ำต่อคอลัมน์แล้วให้เลื่อนแนวนอนแทน
     ของเดิมเป็น flex:1 ล้วน พอเลือก engine ครบ 8 ตัวจะถูกบีบเหลือ 1/8 ของจอ
     ข้อความไทยตัดคำทีละ 2-3 ตัวอักษร อ่านไม่ออกและวรรณยุกต์ซ้อนกันมั่ว
     ยอมให้เลื่อนดีกว่าให้ทุกอันพร้อมกันแต่อ่านไม่ได้สักอัน */
  .cols { display:flex; gap:.75rem; align-items:flex-start;
          overflow-x:auto; padding-bottom:.5rem; }
  .cols > div { flex:1 0 340px; min-width:340px; }

  /* กลุ่มตระกูล engine
     เคยทำหัวกลุ่มเป็น sticky เพื่อให้รู้ตลอดว่าดูตัวไหนอยู่ แต่ผลคือมันลอย
     ไปทับบรรทัดสุดท้ายของกลุ่มก่อนหน้าตอนเลื่อน ซึ่งบังข้อความที่กำลังอ่านอยู่
     แลกไม่คุ้ม เอาออกแล้วทำให้หัวติดเป็นเนื้อเดียวกับกลุ่มของตัวเองแทน
     กล่องครอบทั้งกลุ่มทำให้เห็นขอบเขตชัดโดยไม่ต้องพึ่ง sticky */
  .grp { margin-bottom:1.4rem; border:1px solid var(--border); border-radius:12px;
         overflow:hidden; background:var(--surface-2); }
  .grphead { display:flex; align-items:center; gap:.5rem;
             font-family:var(--mono); font-size:12px; font-weight:700;
             color:#fff; background:var(--accent);
             padding:.45rem .75rem; }
  .grp > .cols { padding:.7rem .7rem 0; }
  .grpcount { font-weight:500; font-size:11px; color:#fff;
              background:rgba(255,255,255,.22); border-radius:999px;
              padding:.1rem .5rem; }

  .card { border:1px solid var(--border); border-radius:12px; padding:.7rem .85rem;
          margin-bottom:.7rem; background:var(--surface); }
  .card.truth { background:var(--accent-soft); border-color:#DCDCFB;
                border-left:4px solid var(--accent); }
  .lab { font-family:var(--mono); font-size:10.5px; font-weight:700; letter-spacing:.09em;
         text-transform:uppercase; color:var(--ink-soft); margin-bottom:.5rem;
         display:flex; align-items:center; gap:.4rem; }
  .lab::before { content:""; width:6px; height:6px; border-radius:50%;
                 background:var(--accent); flex:none; }
  .pill { display:inline-flex; font-family:var(--mono); font-size:11px; font-weight:600;
          padding:.25rem .6rem; border-radius:999px; margin:0 .3rem .3rem 0; }
  .good{background:var(--good-bg);color:var(--good-ink)}
  .warn{background:var(--warn-bg);color:var(--warn-ink)}
  .bad {background:var(--bad-bg); color:var(--bad-ink)}
  .note { font-size:12.5px; line-height:1.6; padding:.5rem .7rem; border-radius:8px;
          margin:.4rem 0; }
  .note.error { background:var(--bad-bg); color:var(--bad-ink); }
  .note.info  { background:var(--accent-soft); color:#3730A3; }

  /* ── บรรทัดข้อความ ── */
  .line { font-size:14.5px; line-height:1.95; padding:.16rem .4rem; border-radius:6px;
          border-left:3px solid transparent; margin:.06rem 0; word-break:break-word;
          transition:background .1s; }
  .line.hit { background:var(--accent-soft); border-left-color:var(--accent); }
  .line.lowconf { border-left-color:#E9A23B; }
  .line.pointable { cursor:crosshair; }
  .line.missed { background:var(--bad-bg); color:var(--bad-ink); font-size:13px; }
  .line.spurious { color:var(--ink-faint); font-size:13px; }
  .wrong { background:var(--bad-bg); color:var(--bad-ink); border-radius:4px; padding:0 3px;
           position:relative; cursor:help; }
  .missing { background:var(--warn-bg); color:var(--warn-ink); border-radius:4px; padding:0 3px;
             text-decoration:underline dotted; text-underline-offset:3px;
             position:relative; cursor:help; }
  .wrong::after, .missing::after {
    content:attr(data-tip); position:absolute; left:50%; bottom:calc(100% + 8px);
    transform:translateX(-50%); background:var(--ink); color:#F5F6F8; font-size:12px;
    padding:.35rem .6rem; border-radius:7px; white-space:normal; width:max-content;
    max-width:240px; box-shadow:0 6px 16px rgba(20,22,27,.24); opacity:0; visibility:hidden;
    pointer-events:none; transition:opacity .1s; z-index:50; font-weight:500; line-height:1.5;
  }
  .wrong:hover::after, .missing:hover::after { opacity:1; visibility:visible; }
  .empty { color:var(--ink-faint); font-size:13px; padding:1rem; text-align:center; }
</style>

<div id="root">
  <div class="bar">
    <span class="title" id="ptitle"></span>
    <div class="seg" id="modeseg">
      <button data-mode="single" class="on">ดูทีละตัว</button>
      <button data-mode="compare">เทียบพร้อมกัน</button>
    </div>
    <button class="btn" id="copybtn">คัดลอกข้อความ</button>
  </div>

  <div class="split">
    <div class="pane-l">
      <div class="imgtools">
        <button class="btn" data-zoom="-1">−</button>
        <span class="zoomval" id="zoomval">100%</span>
        <button class="btn" data-zoom="1">+</button>
        <button class="btn" id="fitbtn">พอดีจอ</button>
        <button class="btn" id="rotbtn">หมุน</button>
        <span class="spacer">ลากเพื่อเลื่อน · ล้อเมาส์เพื่อซูม</span>
      </div>
      <div class="stage" id="stage">
        <div class="canvas" id="canvas">
          <img id="pageimg" />
          <div class="boxes" id="boxes"><div class="bx" id="bx"></div></div>
        </div>
      </div>
    </div>

    <div class="pane-r">
      <div class="tabs" id="tabs"></div>
      <div class="scroll" id="scroll"></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;

// ── ตัวดูรูป: ซูม ลาก หมุน ──────────────────────────────────────────────
const stage  = document.getElementById('stage');
const canvas = document.getElementById('canvas');
const img    = document.getElementById('pageimg');
const bx     = document.getElementById('bx');
const zoomval= document.getElementById('zoomval');

let scale = 1, tx = 0, ty = 0, rot = 0, baseScale = 1;
img.src = DATA.image;

function apply() {
  canvas.style.transform =
    `translate(${tx}px, ${ty}px) scale(${scale}) rotate(${rot}deg)`;
  zoomval.textContent = Math.round(scale / baseScale * 100) + '%';
}

function fit() {
  const sw = stage.clientWidth, sh = stage.clientHeight;
  const iw = img.naturalWidth || 1, ih = img.naturalHeight || 1;
  const swapped = rot % 180 !== 0;
  baseScale = Math.min(sw / (swapped ? ih : iw), sh / (swapped ? iw : ih)) * 0.96;
  scale = baseScale;
  // จัดกึ่งกลางเวที เผื่อกรณีหมุนแล้วกรอบสลับด้าน
  tx = (sw - (swapped ? ih : iw) * scale) / 2 + (swapped ? ih * scale : 0);
  ty = (sh - (swapped ? iw : ih) * scale) / 2;
  apply();
}
img.onload = fit;
window.addEventListener('resize', fit);

stage.addEventListener('wheel', e => {
  e.preventDefault();
  const r = stage.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  const next = Math.min(baseScale * 12, Math.max(baseScale * 0.4, scale * factor));
  // ซูมเข้าหาตำแหน่งเมาส์ ไม่ใช่มุมซ้ายบน
  tx = mx - (mx - tx) * (next / scale);
  ty = my - (my - ty) * (next / scale);
  scale = next; apply();
}, {passive:false});

let dragging = false, lx = 0, ly = 0;
stage.addEventListener('mousedown', e => {
  dragging = true; lx = e.clientX; ly = e.clientY; stage.classList.add('drag');
});
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  tx += e.clientX - lx; ty += e.clientY - ly;
  lx = e.clientX; ly = e.clientY; apply();
});
window.addEventListener('mouseup', () => { dragging = false; stage.classList.remove('drag'); });

document.querySelectorAll('[data-zoom]').forEach(b => b.onclick = () => {
  const f = +b.dataset.zoom > 0 ? 1.25 : 1/1.25;
  const cx = stage.clientWidth/2, cy = stage.clientHeight/2;
  const next = Math.min(baseScale*12, Math.max(baseScale*0.4, scale*f));
  tx = cx - (cx - tx) * (next/scale); ty = cy - (cy - ty) * (next/scale);
  scale = next; apply();
});
document.getElementById('fitbtn').onclick = () => { fit(); };
document.getElementById('rotbtn').onclick = () => { rot = (rot + 90) % 360; fit(); };

// ── ไฮไลต์กรอบบนรูปเมื่อชี้ข้อความ ─────────────────────────────────────
// box เก็บเป็นพิกัดของรูปต้นฉบับ แต่รูปที่แสดงถูกย่อมาแล้ว
// จึงต้องคูณอัตราส่วนก่อนวาด ไม่งั้นกรอบจะเลื่อนไปคนละที่
function showBox(box) {
  if (!box) { bx.classList.remove('on'); return; }
  const k = (img.naturalWidth || DATA.imgW) / DATA.imgW;
  bx.style.left   = (box[0] * k) + 'px';
  bx.style.top    = (box[1] * k) + 'px';
  bx.style.width  = (box[2] * k) + 'px';
  bx.style.height = (box[3] * k) + 'px';
  bx.classList.add('on');
}

// ── ฝั่งผลลัพธ์ ────────────────────────────────────────────────────────
const tabsEl = document.getElementById('tabs');
const scrollEl = document.getElementById('scroll');
let mode = 'single', active = 0;

document.getElementById('ptitle').textContent = DATA.pageTitle;

function lineHTML(ln) {
  const cls = ['line'];
  if (ln.kind === 'missed') cls.push('missed');
  else if (ln.kind === 'spurious') cls.push('spurious');
  if (ln.box) cls.push('pointable');
  if (ln.conf !== null && ln.conf !== undefined && ln.conf < 0.75) cls.push('lowconf');
  const b = ln.box ? ` data-box="${ln.box.join(',')}"` : '';
  const t = (ln.conf !== null && ln.conf !== undefined)
    ? ` title="ความมั่นใจ ${Math.round(ln.conf*100)}%"` : '';
  return `<div class="${cls.join(' ')}"${b}${t}>${ln.html}</div>`;
}

function engineCard(e) {
  const badges = e.badges.map(b => `<span class="pill ${b.tone}">${b.label}</span>`).join('');
  const notes  = e.notes.map(n => `<div class="note ${n.kind}">${n.text}</div>`).join('');
  const noBox  = e.hasBoxes ? '' :
    `<div class="note info">engine นี้ไม่คืนพิกัดข้อความ (API ส่งมาแต่ตัวหนังสือ) จึงชี้ตำแหน่งบนรูปไม่ได้</div>`;
  const lines  = e.lines.length
    ? e.lines.map(lineHTML).join('')
    : '<div class="empty">ไม่มีบรรทัด</div>';
  // ในกลุ่มเดียวกันชื่อ engine ซ้ำกันทุกใบ ต่างกันแค่ภาพต้นทาง จึงขึ้นตัวนั้นแทน
  const label = e.variant || e.name;
  return `<div class="card"><div class="lab">${label}</div>${badges}${notes}${noBox}${lines}</div>`;
}

// จัดกลุ่มตามตระกูล engine โดยคงลำดับเดิมไว้
// ตระกูลเดียวกันต่างกันแค่ภาพต้นทาง (ดิบ / ลบลายน้ำ) ซึ่งเป็นคำถามหลัก
// ของงานนี้พอดี วางคู่กันจึงเทียบได้ทันทีโดยไม่ต้องสลับแท็บไปมา
function groupEngines() {
  const order = [];
  const map = new Map();
  DATA.engines.forEach(e => {
    const g = e.group || e.name;
    if (!map.has(g)) { map.set(g, []); order.push(g); }
    map.get(g).push(e);
  });
  return order.map(g => ({name: g, items: map.get(g)}));
}

function groupBlock(g) {
  const cards = g.items.map(e => `<div>${engineCard(e)}</div>`).join('');
  return `<div class="grp"><div class="grphead">${g.name}` +
    `<span class="grpcount">${g.items.length} แบบ</span></div>` +
    `<div class="cols">${cards}</div></div>`;
}

function truthCard() {
  // หน้าที่ยังไม่มีเฉลย ไม่ต้องขึ้นการ์ดเปล่า มันดูเหมือนเฉลยว่างเปล่า
  if (!DATA.truth.length) return '';
  return `<div class="card truth"><div class="lab">เฉลย</div>` +
    DATA.truth.map(t => `<div class="line">${t}</div>`).join('') + `</div>`;
}

function render() {
  const groups = groupEngines();
  if (active >= groups.length) active = 0;

  // แท็บเป็นตระกูล ไม่ใช่ engine ทีละตัว จาก 11 แท็บเหลือ 6
  tabsEl.innerHTML = mode === 'single'
    ? groups.map((g,i) =>
        `<button class="${i===active?'on':''}" data-i="${i}">${g.name}</button>`).join('')
    : '';
  tabsEl.style.display = mode === 'single' ? 'flex' : 'none';

  if (!DATA.engines.length) {
    scrollEl.innerHTML =
      '<div class="empty">ยังไม่มีผลของ engine ใดในหน้านี้</div>' + truthCard();
    return;
  }

  // เฉลยอยู่ล่างสุด — ผลของ engine ที่กำลังตรวจควรอยู่ใกล้ขอบบนมากที่สุด
  // เพราะเป็นสิ่งที่ต้องกวาดสายตาเทียบกับรูปฝั่งซ้ายตลอดเวลา
  scrollEl.innerHTML = mode === 'single'
    ? groupBlock(groups[active]) + truthCard()
    : groups.map(groupBlock).join('') + truthCard();
}

tabsEl.onclick = e => {
  const b = e.target.closest('button[data-i]');
  if (!b) return;
  active = +b.dataset.i; render();
};

document.getElementById('modeseg').onclick = e => {
  const b = e.target.closest('button[data-mode]');
  if (!b) return;
  mode = b.dataset.mode;
  document.querySelectorAll('#modeseg button')
    .forEach(x => x.classList.toggle('on', x === b));
  render();
};

// hover บรรทัด -> วาดกรอบบนรูป (ใช้ event delegation ครั้งเดียว
// ไม่ผูก listener รายบรรทัด เพราะบางหน้ามีเป็นร้อยบรรทัด)
scrollEl.addEventListener('mouseover', e => {
  const el = e.target.closest('.line[data-box]');
  if (!el) return;
  scrollEl.querySelectorAll('.line.hit').forEach(x => x.classList.remove('hit'));
  el.classList.add('hit');
  showBox(el.dataset.box.split(',').map(Number));
});
scrollEl.addEventListener('mouseleave', () => {
  scrollEl.querySelectorAll('.line.hit').forEach(x => x.classList.remove('hit'));
  showBox(null);
});

document.getElementById('copybtn').onclick = () => {
  const src = mode === 'single' && DATA.engines.length
    ? DATA.engines[active] : null;
  const text = src
    ? src.lines.filter(l => l.kind !== 'missed')
         .map(l => l.html.replace(/<[^>]+>/g, '')).join('\n')
    : DATA.truth.map(t => t.replace(/<[^>]+>/g, '')).join('\n');
  navigator.clipboard.writeText(text).then(() => {
    const b = document.getElementById('copybtn');
    const old = b.textContent; b.textContent = 'คัดลอกแล้ว';
    setTimeout(() => b.textContent = old, 1200);
  });
};

render();
</script>
"""
