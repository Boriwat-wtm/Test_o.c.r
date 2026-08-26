"""ครอปบรรทัดเดียวออกจากหน้าเต็มแล้วขยาย — ใช้ร่วมกันระหว่างตัวรันกับหน้าเว็บ

ทำไมต้องอยู่ที่เดียว: rescue.py ครอปแบบหนึ่ง (เผื่อขอบ 200x16 ขยาย 4 เท่า)
ส่วนหน้าเว็บเคยครอปอีกแบบ (เผื่อขอบ 12 ขยายเฉพาะบรรทัดเตี้ย) ผลคือภาพที่คน
เห็นบนจอไม่ใช่ภาพที่ engine อ่านจริง แล้วไม่มีอะไรบอกด้วยว่าคนละภาพกัน
คนตรวจจึงสรุปผิดได้ว่า "engine เห็นชัดขนาดนี้ยังอ่านผิด"

ค่าคงที่ทุกตัวจึงอยู่ในไฟล์นี้ที่เดียว ใครจะแสดงหรือจะอ่าน ต้องได้ภาพเดียวกัน
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# ครอปชิดตัวอักษรเกินไปจะตัดวรรณยุกต์บนกับสระล่างทิ้ง ซึ่งเป็นตัวที่ต้องอ่านที่สุด
PAD_Y = 16
# แนวนอนเผื่อเยอะกว่ามาก เพราะกล่องที่ยืมมามักจบก่อนตัวอักษรตัวสุดท้ายของบรรทัด
# 200 px ที่ 300 DPI ราวสองเซนติเมตร พอครอบส่วนที่ engine ตีกรอบพลาด
PAD_X = 200
# ขยายให้ตัวหนังสือใหญ่ขึ้น เป็นหัวใจของ self-rescue — บรรทัดที่ย่อรวมมากับทั้งหน้า
# จะมีความละเอียดต่อตัวอักษรต่ำกว่าตอนส่งไปเดี่ยว ๆ มาก
ZOOM = 4
# ไม่ให้ภาพครอปใหญ่เกินจำเป็น เปลืองโทเคนเปล่า ๆ
MAX_WIDTH = 3000


def crop_region(
    image_path: Path, box: tuple[int, int, int, int]
) -> Image.Image | None:
    """คืนภาพบรรทัดเดียวที่ขยายแล้ว — ภาพเดียวกับที่ engine เห็นตอนอ่านซ้ำ

    เผื่อขอบแนวนอนมากกว่าแนวตั้ง เพราะกล่องที่ยืมมาพลาดคนละแบบในสองแกน
    ตำแหน่งแนวตั้งของบรรทัดแม่นกว่าขอบเขตแนวนอนมาก

    เคยลองครอปเต็มความกว้างหน้าเทียบด้วย ผลออกมาเท่ากันทุกตัวเลข
    จึงเลือกครอปตามกล่องเพราะภาพเล็กกว่า ประหยัดโทเคน
    """
    if not image_path.exists():
        return None
    with Image.open(image_path) as im:
        x, y, w, h = box
        area = (
            max(0, x - PAD_X),
            max(0, y - PAD_Y),
            min(im.width, x + w + PAD_X),
            min(im.height, y + h + PAD_Y),
        )
        piece = im.crop(area).convert("RGB")

    scale = min(ZOOM, MAX_WIDTH / max(piece.width, 1))
    if scale > 1:
        piece = piece.resize(
            (int(piece.width * scale), int(piece.height * scale)), Image.LANCZOS
        )
    return piece


def crop_to_file(image_path: Path, box: tuple[int, int, int, int], out: Path) -> bool:
    """ครอปแล้วเขียนเป็นไฟล์ให้ engine อ่าน คืน False ถ้าไม่มีภาพต้นทาง"""
    piece = crop_region(image_path, box)
    if piece is None:
        return False
    piece.save(out)
    return True
