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


def has_watermark(image: Image.Image, min_ratio: float = 0.005) -> bool:
    """มีลายน้ำให้ลบไหม — ถ้าไม่มีก็ไม่ควรแตะภาพเลย"""
    return detect_light_layer(image) >= min_ratio


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
