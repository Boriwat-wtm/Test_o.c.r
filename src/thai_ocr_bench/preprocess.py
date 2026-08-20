"""เตรียมภาพก่อนเข้า OCR

ตอนนี้มีอย่างเดียวคือลบลายน้ำ ซึ่งแก้ปัญหาหลายอย่างพร้อมกันในที่เดียว
  - Typhoon ติดลูปพ่นข้อความลายน้ำซ้ำ 123 บรรทัดจนชนเพดาน token
  - PaddleOCR พ่นบรรทัดเกิน 438 บรรทัด และอ่านครบแค่ 70%
  - เฉลยตัดลายน้ำออกแล้ว แต่ OCR อ่านเจอ การเทียบจึงไม่เป็นธรรม

แก้ที่ภาพครั้งเดียวได้ผลกับทุก engine ต่างจากไปแก้ที่ตัว engine ทีละตัว

หลักการ: วัดการกระจายค่าความสว่างของหน้าจริงแล้วพบสองกลุ่มแยกกันชัด
    0-63     1.7%   ตัวหนังสือจริง (ดำเข้ม)
    230-244  1.8%   ลายน้ำ (เทาจาง)
    245-255  95.3%  พื้นขาว
จุดตัดที่ 215 จึงอยู่กลางช่องว่างระหว่างสองกลุ่ม ตัดลายน้ำได้โดยไม่แตะตัวหนังสือ

ข้อควรระวัง: ค่านี้วัดจากเอกสารชุดนี้ ถ้าเปลี่ยนเอกสารต้องวัดใหม่
ใช้ suggest_threshold() หาค่าที่เหมาะกับภาพนั้น ๆ ได้
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# จุดตัดเริ่มต้น วัดจากเอกสารกฎหมายที่ดินในชุดทดสอบ
DEFAULT_THRESHOLD = 215


def remove_watermark(
    image: Image.Image, threshold: int = DEFAULT_THRESHOLD
) -> Image.Image:
    """ลบสิ่งที่จางกว่าจุดตัดออกให้เป็นพื้นขาว

    คงค่าเดิมของพิกเซลที่เข้มกว่าจุดตัดไว้ทั้งหมด ไม่ทำเป็นขาวดำสองระดับ
    เพราะการทิ้งเฉดกลางไปจะทำให้ขอบสระกับวรรณยุกต์ที่บางอยู่แล้วขาดหาย
    """
    gray = np.asarray(image.convert("L"))
    cleaned = np.where(gray >= threshold, 255, gray).astype(np.uint8)
    return Image.fromarray(cleaned, mode="L")


def detect_light_layer(image: Image.Image) -> float:
    """สัดส่วนพิกเซลที่อยู่ในช่วงเทาจาง ซึ่งเป็นลายเซ็นของลายน้ำ

    หน้าที่มีลายน้ำจะมีก้อนพิกเซลชัดเจนในช่วง 215-244 (จางกว่าตัวหนังสือมาก
    แต่ไม่ขาวสนิท) หน้าที่ไม่มีลายน้ำจะแทบไม่มีพิกเซลในช่วงนี้เลย

    เคยลองให้หา "หลุม" ที่เงียบที่สุดในฮิสโทแกรมแล้วเดาจุดตัดเอง แต่วิธีนั้นผิด
    มันไปเลือกค่าราว 165 ซึ่งกินขอบตัวอักษรทิ้งไป 48% แม้ในหน้าที่ไม่มีลายน้ำ
    เพราะจุดที่เงียบที่สุดคือช่องว่างระหว่างตัวหนังสือกับขอบ ไม่ใช่ระหว่าง
    ตัวหนังสือกับลายน้ำ จึงเปลี่ยนมาตรวจว่ามีก้อนเทาจางอยู่จริงไหมแทน
    """
    gray = np.asarray(image.convert("L"))
    return float(((gray >= DEFAULT_THRESHOLD) & (gray < 245)).mean())


def separation(image: Image.Image) -> float:
    """ก้อนเทาจางแยกตัวออกมาชัดแค่ไหน = ขนาดก้อน (230-244) หารด้วยความลึกหลุม (200-229)

    ตัวนี้มีไว้แยกลายน้ำออกจากภาพสแกนพื้นเทา ซึ่ง detect_light_layer แยกไม่ออก
    เพราะมันนับแค่ว่าช่วง 215-244 มีพิกเซลเยอะไหม แต่สแกนก็มีเยอะเหมือนกัน
    จากขอบตัวอักษรที่ถูก anti-alias ทำให้สแกนธรรมดาถูกตัดสินว่ามีลายน้ำ

    ความต่างอยู่ที่รูปทรงของฮิสโทแกรม วัดจากหน้าจริงในชุดทดสอบ
        กฏหมาย (ลายน้ำจริง)  200-229 = 0.27%  230-244 = 1.77%  ratio 6.6
        นโยบาย (สแกน)        200-229 = 1.46%  230-244 = 2.11%  ratio 1.4
        คำสั่ง  (สแกน)        200-229 = 1.20%  230-244 = 3.28%  ratio 2.7
    ลายน้ำเป็นเฉดเดียวจึงกองอยู่ที่เดียวโดยมีหลุมว่างคั่นก่อนถึงตัวหนังสือ
    ส่วนสแกนไล่เฉดต่อเนื่องจากดำไปขาว ไม่มีหลุม
    """
    gray = np.asarray(image.convert("L"))
    valley = float(((gray >= 200) & (gray < 230)).mean())
    bump = float(((gray >= 230) & (gray < 245)).mean())
    if valley <= 0:
        return float("inf") if bump > 0 else 0.0
    return bump / valley


def has_watermark(
    image: Image.Image, min_ratio: float = 0.005, min_separation: float = 4.0
) -> bool:
    """มีลายน้ำให้ลบไหม — ถ้าไม่มีก็ไม่ควรแตะภาพเลย

    ต้องผ่านทั้งสองข้อ มีก้อนเทาจางมากพอ และก้อนนั้นแยกตัวจริงไม่ใช่แค่
    ขอบตัวอักษรของภาพสแกน จุดตัด 4.0 อยู่กลางช่องว่างระหว่างสองกลุ่มที่วัดได้
    """
    return (
        detect_light_layer(image) >= min_ratio and separation(image) >= min_separation
    )


def ink_ratio(image: Image.Image, threshold: int = DEFAULT_THRESHOLD) -> float:
    """สัดส่วนพิกเซลที่เป็นหมึก ใช้ตรวจว่าการลบไม่ได้กินตัวหนังสือไปด้วย"""
    gray = np.asarray(image.convert("L"))
    return float((gray < threshold).mean())


def clean_file(
    src: Path, dst: Path, threshold: int = DEFAULT_THRESHOLD, *, always: bool = False
) -> tuple[float, float, bool]:
    """ลบลายน้ำจากไฟล์ภาพ คืน (สัดส่วนชั้นจางก่อน, หลัง, ลบจริงไหม)

    หน้าที่ไม่มีลายน้ำจะคัดลอกไปตรง ๆ ไม่แตะ เพื่อไม่ให้ขอบตัวอักษรบางลง
    โดยไม่จำเป็น ส่งตั้ง always=True ถ้าต้องการบังคับลบทุกหน้า
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as raw:
        image = raw.convert("L")
        before = detect_light_layer(image)
        should = always or has_watermark(image)
        output = remove_watermark(image, threshold) if should else image
        after = detect_light_layer(output)
        output.save(dst)
    return before, after, should
