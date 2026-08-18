"""จัดข้อความไทยให้อยู่ในรูปมาตรฐานก่อนนำไปวัดผล

ถ้าโมดูลนี้ผิด ตัวเลขทั้ง benchmark ผิดหมด จึงต้องมีเทสต์ของตัวเองเสมอ
(ดู tests/test_thai_text.py)

ปัญหาที่โมดูลนี้แก้
  1. สระกับวรรณยุกต์เขียนสลับลำดับได้ แต่แสดงผลเหมือนกัน — NFC ของ Unicode
     ไม่ช่วย เพราะสระไทยส่วนใหญ่มี combining class = 0 จึงไม่ถูกจัดลำดับใหม่
  2. "ำ" เขียนเป็นตัวเดียว (U+0E33) หรือเป็น นิคหิต + สระอา ก็ได้
  3. OCR บางตัวพ่นวรรณยุกต์ซ้ำติดกัน
  4. ภาษาไทยไม่เว้นวรรคระหว่างคำ แต่ละ engine จึงใส่ช่องว่างไม่เหมือนกัน
"""

from __future__ import annotations

import re
import unicodedata

# ── ลำดับมาตรฐานของเครื่องหมายที่เกาะอยู่กับพยัญชนะ ────────────────────────
# เลขน้อยมาก่อน เรียงแบบ stable เพื่อไม่สลับตัวที่ลำดับเท่ากัน
_MARK_RANK: dict[str, int] = {
    # สระล่าง
    "ุ": 1,  # ุ
    "ู": 1,  # ู
    "ฺ": 1,  # ฺ พินทุ
    # สระบน
    "ั": 2,  # ั ไม้หันอากาศ
    "ิ": 2,  # ิ
    "ี": 2,  # ี
    "ึ": 2,  # ึ
    "ื": 2,  # ื
    "็": 2,  # ็ ไม้ไต่คู้
    # วรรณยุกต์
    "่": 3,  # ่
    "้": 3,  # ้
    "๊": 3,  # ๊
    "๋": 3,  # ๋
    # เครื่องหมายบนสุด
    "์": 4,  # ์ ทัณฑฆาต
    "ํ": 4,  # ํ นิคหิต
    "๎": 4,  # ๎ ยามักการ
}

THAI_DIGITS = "๐๑๒๓๔๕๖๗๘๙"
_THAI_TO_ARABIC = str.maketrans(THAI_DIGITS, "0123456789")

# ── ตัวอักษรที่หน้าตาต่างกันแต่ความหมายเดียวกัน ────────────────────────
# ต้นฉบับใช้อัญประกาศโค้ง (“ ”) ส่วน VLM อย่าง Typhoon คืนอัญประกาศตรง (")
# ถ้าไม่ยุบให้เหมือนกันก่อน จะถูกนับเป็นอ่านผิดทั้งที่อ่านถูก — หน้าเดียวโดนไป ๓๐ จุด
# ยุบทั้งสองฝั่งเสมอ จึงไม่มี engine ไหนได้เปรียบ
#
# เลขยกกำลัง (¹ ⁰) จงใจแปลงเป็นเลขอารบิก ไม่ใช่เลขไทย
# เพราะ Typhoon อ่านเลขเชิงอรรถที่เป็นเลขไทยยกกำลัง (๑๐) ออกมาเป็น ¹⁰
# ซึ่งเป็น "ค่าถูกแต่ไม่ใช่เลขไทย" แปลงแบบนี้การวัดจะรายงานตรงความจริง
# strict ตก (เสียความเป็นเลขไทย) แต่ lenient ผ่าน (ค่ากู้คืนได้)
# เหมือนกรณี PaddleOCR ที่พ่นเลขอารบิกออกมา
_TYPOGRAPHY = str.maketrans(
    {
        **dict.fromkeys("“”„‟«»", '"'),
        **dict.fromkeys("‘’‚‛", "'"),
        **dict.fromkeys("‐‑‒–—―−", "-"),
        **dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")),
        **dict(zip("₀₁₂₃₄₅₆₇₈₉", "0123456789")),
    }
)


def fold_typography(text: str) -> str:
    """ยุบอักขระที่ต่างกันแค่รูปแบบการพิมพ์ให้เหลือรูปเดียว"""
    return text.translate(_TYPOGRAPHY)

_SARA_AM = "ำ"  # ำ
_NIKHAHIT = "ํ"  # ํ
_SARA_AA = "า"  # า


def is_mark(ch: str) -> bool:
    """เป็นเครื่องหมายที่เกาะพยัญชนะหรือไม่ (ไม่กินที่ในบรรทัด)"""
    return ch in _MARK_RANK


def compose_sara_am(text: str) -> str:
    """รวม นิคหิต + สระอา ให้เป็น ำ ตัวเดียว

    OCR บางตัวมองเห็นเป็นสองส่วนแยกกัน ถ้าไม่รวมก่อนจะถูกนับว่าผิดทั้งที่อ่านถูก
    """
    return text.replace(_NIKHAHIT + _SARA_AA, _SARA_AM)


def reorder_marks(text: str) -> str:
    """เรียงเครื่องหมายที่ตามหลังพยัญชนะแต่ละตัวให้เป็นลำดับมาตรฐาน"""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            out.extend(sorted(run, key=lambda c: _MARK_RANK[c]))
            run.clear()

    for ch in text:
        if is_mark(ch):
            run.append(ch)
        else:
            flush()
            out.append(ch)
    flush()
    return "".join(out)


def drop_duplicate_marks(text: str) -> str:
    """ตัดเครื่องหมายชนิดเดียวกันที่ซ้ำติดกันให้เหลือตัวเดียว

    ไทยไม่มีคำไหนใช้วรรณยุกต์ตัวเดียวกันซ้อนกันสองครั้ง ถ้าเจอแปลว่า OCR พ่นซ้ำ
    """
    out: list[str] = []
    for ch in text:
        if is_mark(ch) and out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def thai_to_arabic_digits(text: str) -> str:
    """แปลงเลขไทย ๐-๙ เป็นเลขอารบิก 0-9 (ใช้กับการวัดแบบ lenient)"""
    return text.translate(_THAI_TO_ARABIC)


def collapse_whitespace(text: str) -> str:
    """ยุบช่องว่างทุกชนิดให้เหลือช่องเดียว และตัดหัวท้าย"""
    return re.sub(r"\s+", " ", text).strip()


def strip_whitespace(text: str) -> str:
    """ตัดช่องว่างทิ้งทั้งหมด — ใช้เป็นค่าตั้งต้นของการวัด CER ภาษาไทย"""
    return re.sub(r"\s+", "", text)


def normalize(text: str, *, keep_spaces: bool = False) -> str:
    """ทำให้ข้อความอยู่ในรูปมาตรฐานก่อนเทียบ

    ลำดับสำคัญ: ต้องรวม ำ ก่อนเรียงลำดับ ไม่งั้นนิคหิตจะถูกย้ายออกจากสระอา
    """
    text = unicodedata.normalize("NFC", text)
    text = fold_typography(text)
    text = compose_sara_am(text)
    text = reorder_marks(text)
    text = drop_duplicate_marks(text)
    return collapse_whitespace(text) if keep_spaces else strip_whitespace(text)


# ── การจัดกลุ่มอักขระ เพื่อวัดความแม่นแยกตามชนิด ─────────────────────────
CHAR_CLASSES = (
    "thai_consonant",
    "thai_vowel_mark",
    "thai_digit",
    "arabic_digit",
    "latin",
    "punct_symbol",
    "other",
)

CLASS_LABELS_TH = {
    "thai_consonant": "พยัญชนะไทย",
    "thai_vowel_mark": "สระ/วรรณยุกต์",
    "thai_digit": "เลขไทย",
    "arabic_digit": "เลขอารบิก",
    "latin": "อักษรละติน",
    "punct_symbol": "เครื่องหมาย",
    "other": "อื่น ๆ",
}

# สระที่กินที่ในบรรทัด (เขียนหน้า หลัง หรือคร่อมพยัญชนะ)
_SPACING_VOWELS = "ะาำเแโใไๅ"

# สัญลักษณ์ไทยที่ทำหน้าที่เหมือนเครื่องหมายวรรคตอน ไม่ใช่สระ
_THAI_SYMBOLS = "ฯๆ๏๚๛฿"


def classify_char(ch: str) -> str:
    """บอกว่าอักขระตัวนี้อยู่กลุ่มไหน ใช้สำหรับความแม่นรายกลุ่ม"""
    if "๐" <= ch <= "๙":
        return "thai_digit"
    if "0" <= ch <= "9":
        return "arabic_digit"
    if ch in _THAI_SYMBOLS:
        return "punct_symbol"
    if "ก" <= ch <= "ฮ":  # ก-ฮ รวม ฤ ฦ ตามลำดับพยัญชนะไทย
        return "thai_consonant"
    if is_mark(ch) or ch in _SPACING_VOWELS or 0x0E00 <= ord(ch) <= 0x0E7F:
        return "thai_vowel_mark"
    if ch.isascii() and ch.isalpha():
        return "latin"
    if not ch.isalnum() and not ch.isspace():
        return "punct_symbol"
    return "other"
