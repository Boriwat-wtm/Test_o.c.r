"""ตัวช่วยที่หลายแท็บใช้ร่วมกัน — โหลดข้อมูล ครอปภาพ จัดกลุ่ม engine

กฎของไฟล์นี้: ห้ามมี st.* ที่วาดอะไรลงหน้าจอ มีได้แต่ cache กับการคำนวณ
ถ้าเริ่มวาด แปลว่ามันเป็นของแท็บใดแท็บหนึ่ง ให้ย้ายไปไฟล์ของแท็บนั้น
"""

from __future__ import annotations

import base64
import io
from collections import Counter
from pathlib import Path

import streamlit as st
from PIL import Image

from ..config import CLEAN_IMAGE_DIR, IMAGE_DIR
from ..render import PageInfo, load_pages
from ..truth import find_repeating_lines
from ..viewer import encode_image

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



def short_doc(name: str, limit: int = 22) -> str:
    """ชื่อเอกสารสั้นพอใส่แถบข้างได้ ชื่อจริงบางอันยาว 40 ตัว"""
    return name if len(name) <= limit else name[: limit - 1] + "…"



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



def page_label(p: PageInfo) -> str:
    return f"{p.doc_name} · หน้า {p.page_no}"



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


