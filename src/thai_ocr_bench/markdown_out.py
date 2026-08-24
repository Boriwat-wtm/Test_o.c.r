"""ส่งผล OCR ออกเป็นไฟล์ markdown ที่คนแก้ต่อได้

ทำไมต้องเป็น markdown ไม่ใช่ข้อความเปล่า
    เอกสารราชการมีโครงสร้าง (หัวข้อ ตาราง เชิงอรรถ) ที่ VLM อ่านออกมาให้แล้ว
    Typhoon คืน "## กรมทะเบียนที่ดิน" มาตรง ๆ ถ้าบันทึกเป็นข้อความเปล่า
    โครงสร้างนั้นหายไปเปล่า ๆ ทั้งที่ engine อุตส่าห์อ่านมาให้

ทำไมต้องแยกไฟล์ต่อ (เอกสาร × engine) ไม่ใช่รวมไฟล์เดียว
    ผลของแต่ละ engine คนละคุณภาพกัน คนแก้ต้องเลือกตัวตั้งต้นที่ดีที่สุดก่อน
    ถ้ารวมไฟล์เดียวจะแก้ทับกันเอง แล้วไม่รู้ว่าที่แก้ไปอยู่บนฐานของตัวไหน

ไฟล์ที่คนแก้แล้วสำคัญกว่าผลดิบ — load() จึงคืนของที่บันทึกไว้ก่อนเสมอ
ไม่ไปสร้างใหม่ทับ ไม่งั้นงานที่คนนั่งแก้มาทั้งวันหายในคลิกเดียว
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import ROOT

EXPORT_DIR = ROOT / "exports"

# คั่นหน้าด้วย comment ของ markdown เพราะมองไม่เห็นตอน render เป็นเอกสารจริง
# แต่ยังอยู่ในไฟล์ให้คนหาหน้าเจอตอนแก้ ใช้ heading (##) ไม่ได้เพราะชนกับ
# หัวข้อที่ Typhoon อ่านมาจากตัวเอกสารเอง ซึ่งก็เป็น ## เหมือนกัน
_PAGE_MARK = "<!-- หน้า {no} · {page_id} -->"


def _safe(name: str) -> str:
    """ชื่อเอกสารมาจากชื่อไฟล์ PDF ซึ่งมีอักขระที่ Windows ห้ามใช้ในชื่อไฟล์ได้

    ไม่ใช้ hash เพราะคนต้องหาไฟล์เจอเองในโฟลเดอร์ ชื่อต้องยังอ่านออก
    """
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", name).strip(". ")
    return cleaned[:120] or "ไม่มีชื่อ"


def path_for(doc_name: str, engine: str) -> Path:
    return EXPORT_DIR / f"{_safe(doc_name)} · {_safe(engine)}.md"


def page_path_for(page_id: str, engine: str) -> Path:
    return EXPORT_DIR / "pages" / f"{_safe(page_id)} · {_safe(engine)}.md"


def save_page(page_id: str, engine: str, text: str) -> Path:
    """เก็บฉบับที่คนแก้ของ "หน้าเดียว" — ใช้ตอนแก้จากแท็บเปรียบเทียบ

    แยกไฟล์รายหน้าแทนที่จะไปแก้กลางไฟล์รวมของทั้งเอกสาร เพราะการหาตำแหน่ง
    ของหน้านั้นในไฟล์รวมแล้วเขียนทับเฉพาะช่วง ต้องแยกไฟล์กลับเป็นหน้า ๆ ก่อน
    ซึ่งพังทันทีถ้าคนเผลอแก้เครื่องหมายคั่นหน้า — เสี่ยงกินงานทั้งเอกสาร
    ไฟล์รายหน้าแยกกันอยู่แล้ว จะพังก็พังแค่หน้าเดียว
    """
    path = page_path_for(page_id, engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_page(page_id: str, engine: str) -> str | None:
    path = page_path_for(page_id, engine)
    return path.read_text(encoding="utf-8") if path.exists() else None


def clear_page(page_id: str, engine: str) -> None:
    page_path_for(page_id, engine).unlink(missing_ok=True)


def build(doc_name: str, engine: str, pages: list[tuple[int, str, list[str]]]) -> str:
    """ประกอบ markdown จากผลดิบ

    pages คือ [(เลขหน้า, page_id, บรรทัดที่อ่านได้)] เรียงตามหน้าแล้ว

    บรรทัดที่ engine อ่านมาปล่อยผ่านตามเดิมทุกตัว ไม่แตะ ไม่จัดรูปแบบเพิ่ม
    ถ้ามันมี markdown มาอยู่แล้ว (Typhoon) ก็ติดไปด้วย ถ้าไม่มีก็เป็นข้อความเปล่า
    หน้าที่นี่คือ "ห่อ" ไม่ใช่ "แปลง" — การไปเดาว่าบรรทัดไหนควรเป็นหัวข้อ
    คือการเดาแทน engine ซึ่งเป็นคนละเรื่องกับการวัดว่า engine อ่านได้แค่ไหน

    หน้าไหนที่คนแก้ไว้แล้วจากแท็บเปรียบเทียบ จะใช้ฉบับที่แก้แทนผลดิบ
    ไม่งั้นกดส่งออกทีเดียวงานที่แก้มาทีละหน้าหายหมด
    """
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    edited = 0
    body: list[str] = []
    for no, page_id, lines in pages:
        body += ["---", "", _PAGE_MARK.format(no=no, page_id=page_id), ""]
        if (fixed := load_page(page_id, engine)) is not None:
            edited += 1
            body += fixed.rstrip("\n").splitlines() or ["*(ไม่มีข้อความ)*"]
        else:
            body += lines if lines else ["*(ไม่มีข้อความ)*"]
        body.append("")

    note = f" · แก้ด้วยมือแล้ว {edited} หน้า" if edited else ""
    head = [
        f"# {doc_name}",
        "",
        f"> อ่านด้วย `{engine}` · {len(pages)} หน้า{note} · สร้างเมื่อ {stamp}  ",
        "> แก้ตรงนี้ได้เลย กดบันทึกแล้วไฟล์นี้จะถูกเขียนทับด้วยฉบับที่แก้",
        "",
    ]
    return "\n".join(head + body).rstrip() + "\n"


def save(doc_name: str, engine: str, text: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = path_for(doc_name, engine)
    path.write_text(text, encoding="utf-8")
    return path


def load(doc_name: str, engine: str) -> str | None:
    """คืนฉบับที่คนแก้แล้ว ถ้ายังไม่เคยบันทึกคืน None ให้ผู้เรียกไปสร้างใหม่เอง"""
    path = path_for(doc_name, engine)
    return path.read_text(encoding="utf-8") if path.exists() else None
