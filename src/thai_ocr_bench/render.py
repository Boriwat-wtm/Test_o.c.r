"""แปลง PDF เป็นภาพ PNG สำหรับป้อนเข้า OCR

จุดสำคัญสองข้อ

1. ต้องเคารพค่า /Rotate ของแต่ละหน้า
   ไฟล์ในชุดทดสอบมีทั้ง 90° และ 270° ปนกัน ถ้าดึงภาพดิบออกมาเฉย ๆ
   ทุกหน้าจะเข้า OCR แบบตะแคง แล้วเราจะสรุปผิดว่า engine อ่านไทยไม่ได้
   PyMuPDF จัดการให้อัตโนมัติเมื่อ render ผ่าน get_pixmap()

2. ทุก engine ต้องได้รับ "ภาพ" เท่านั้น
   ไฟล์ที่มี text layer ห้ามส่ง PDF เข้า engine ตรง ๆ เพราะบางตัวจะไปดึง
   ข้อความจาก text layer แทนที่จะอ่านภาพ แล้วได้คะแนนเต็มโดยไม่ได้ทดสอบอะไร
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

from .config import IMAGE_DIR, RENDER_DPI, SOURCE_DIR, ensure_dirs


@dataclass
class PageInfo:
    page_id: str
    doc_id: str
    doc_name: str
    page_no: int  # เริ่มที่ 1
    image: str  # path สัมพัทธ์กับรากโปรเจกต์
    width: int
    height: int
    rotation: int  # ค่า /Rotate ที่อ่านได้จากไฟล์
    portrait: bool
    has_text_layer: bool
    text_chars: int  # จำนวนตัวอักษรใน text layer (0 = เป็นภาพสแกนล้วน)


def doc_id_for(path: Path) -> str:
    """ไอดีสั้น ๆ ที่คงที่ ผูกกับชื่อไฟล์ ไม่เลื่อนเมื่อเพิ่มไฟล์ใหม่"""
    digest = hashlib.md5(path.name.encode("utf-8")).hexdigest()[:6]
    return f"doc{digest}"


def render_all(
    source_dir: Path | None = None,
    dpi: int = RENDER_DPI,
    *,
    force: bool = False,
) -> list[PageInfo]:
    """แปลงทุกหน้าของทุก PDF ในโฟลเดอร์ต้นทางเป็น PNG แล้วคืนรายการหน้า"""
    ensure_dirs()
    source_dir = source_dir or SOURCE_DIR
    pdfs = sorted(source_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"ไม่พบไฟล์ PDF ใน {source_dir}")

    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    pages: list[PageInfo] = []

    for pdf_path in pdfs:
        doc_id = doc_id_for(pdf_path)
        with pymupdf.open(pdf_path) as doc:
            for idx, page in enumerate(doc, start=1):
                page_id = f"{doc_id}_p{idx:03d}"
                out_path = IMAGE_DIR / f"{page_id}.png"

                if force or not out_path.exists():
                    # get_pixmap ใช้ค่า rotation ของหน้าอยู่แล้ว ภาพที่ได้จึงตั้งตรง
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    pix.save(out_path)
                    width, height = pix.width, pix.height
                else:
                    rect = page.rect * zoom
                    width, height = round(rect.width), round(rect.height)

                text = page.get_text("text").strip()
                pages.append(
                    PageInfo(
                        page_id=page_id,
                        doc_id=doc_id,
                        doc_name=pdf_path.stem,
                        page_no=idx,
                        image=str(out_path.relative_to(IMAGE_DIR.parents[1])),
                        width=width,
                        height=height,
                        rotation=page.rotation,
                        portrait=height >= width,
                        has_text_layer=bool(text),
                        text_chars=len(text),
                    )
                )

    manifest = IMAGE_DIR.parent / "pages.json"
    manifest.write_text(
        json.dumps([asdict(p) for p in pages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return pages


def load_pages() -> list[PageInfo]:
    manifest = IMAGE_DIR.parent / "pages.json"
    if not manifest.exists():
        return []
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    return [PageInfo(**r) for r in raw]
