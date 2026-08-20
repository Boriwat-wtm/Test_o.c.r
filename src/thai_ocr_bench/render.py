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
from PIL import Image

from .config import IMAGE_DIR, RENDER_DPI, SOURCE_DIR, ensure_dirs

# ต่ำกว่านี้ถือว่าหน้าเป็นสแกนความละเอียดต่ำ ไม่มีอะไรให้ขยาย
# 90 เผื่อไว้เหนือ 72 พอให้สแกนที่ตั้งใจทำมาที่ 96 DPI ไม่โดนลูกหลง
NATIVE_DPI_FLOOR = 90


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


def _native_dpi(page: pymupdf.Page) -> float:
    """ความละเอียดจริงสูงสุดที่หน้านี้มี คิดจากภาพทุกรูปบนหน้า (0 = ไม่มีภาพเลย)

    get_image_info ให้ทั้งขนาดพิกเซลของภาพและกรอบที่ภาพถูกวางจริงบนหน้า
    หารกันจึงได้ DPI ที่ภาพนั้นให้จริง ๆ ตรงตำแหน่งที่มันอยู่

    ต้องคิดจากกรอบที่วาง ไม่ใช่ขนาดหน้า เพราะสองเหตุผล
      - โลโก้หรือตราประทับเล็ก ๆ ความละเอียดต่ำจะลากทั้งหน้าลงไปด้วย
      - page.rect เป็นค่าหลังหมุนแล้ว แต่พิกเซลของภาพเป็นค่าดิบ พอหารกัน
        บนหน้า 90°/270° อัตราส่วนจะเพี้ยนไปตามด้านที่สลับกัน

    เอาค่าสูงสุดเพราะหน้าที่มีภาพพื้นหลังหยาบแต่มีเอกสารความละเอียดสูงแปะทับ
    ต้อง render ตามตัวที่ละเอียดที่สุด ไม่งั้นรายละเอียดที่มีอยู่จริงจะหายไป
    """
    best = 0.0
    for info in page.get_image_info(xrefs=True):
        rect = pymupdf.Rect(info["bbox"])
        if not rect.width or not rect.height:
            continue
        dpi = max(info["width"] / rect.width, info["height"] / rect.height) * 72
        best = max(best, dpi)
    return best


def _capped_zoom(page: pymupdf.Page, zoom: float) -> float:
    """ลด zoom ถ้าหน้านี้เป็นภาพสแกนที่ความละเอียดจริงต่ำกว่าที่เราตั้งใจ render

    บางไฟล์สแกนตั้งขนาดหน้าผิด (px ถูกใส่เป็น pt ตรง ๆ) ทำให้ implied DPI ~72
    ถ้าใช้ zoom = dpi/72 ตามปกติจะเอาภาพสแกนที่มีความละเอียดพอแล้วไปขยายซ้ำอีกหลายเท่า
    โดยไม่ได้รายละเอียดเพิ่มขึ้นจริง แค่ทำไฟล์ใหญ่ขึ้นเปล่า ๆ
    """
    native = _native_dpi(page)
    if native == 0 or native >= NATIVE_DPI_FLOOR:
        return zoom
    # หน้าที่มี text layer หรือเส้น vector ไม่ได้ถูกจำกัดด้วยความละเอียดของภาพ
    # ยิ่ง render ละเอียดยิ่งได้ตัวหนังสือคมขึ้นจริง จึงห้าม cap
    if page.get_text("text").strip() or page.get_drawings():
        return zoom
    # ไม่ลดต่ำกว่า 1.0 เพราะต่ำกว่านั้นคือย่อให้เล็กกว่าขนาดหน้าเป็น pt
    return min(zoom, max(native / 72, 1.0))


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
    pages: list[PageInfo] = []

    for pdf_path in pdfs:
        doc_id = doc_id_for(pdf_path)
        with pymupdf.open(pdf_path) as doc:
            for idx, page in enumerate(doc, start=1):
                page_id = f"{doc_id}_p{idx:03d}"
                out_path = IMAGE_DIR / f"{page_id}.png"

                if force or not out_path.exists():
                    page_zoom = _capped_zoom(page, zoom)
                    matrix = pymupdf.Matrix(page_zoom, page_zoom)
                    # get_pixmap ใช้ค่า rotation ของหน้าอยู่แล้ว ภาพที่ได้จึงตั้งตรง
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    pix.save(out_path)
                    width, height = pix.width, pix.height
                else:
                    # อ่านขนาดจากไฟล์จริง ไม่คำนวณย้อนจาก zoom เพราะภาพที่ค้างอยู่
                    # อาจถูก render ด้วยเกณฑ์หรือ dpi คนละชุดกับรอบนี้ แล้ว pages.json
                    # จะไม่ตรงกับไฟล์บนดิสก์แบบเงียบ ๆ ทั้งที่ขั้นครอปเอาไปใช้ต่อ
                    with Image.open(out_path) as cached:
                        width, height = cached.size

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
