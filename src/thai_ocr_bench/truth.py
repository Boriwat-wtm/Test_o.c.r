"""จัดการเฉลย (ground truth)

เฉลยมาได้สองทาง
  1. ดึงจาก text layer ของ PDF ที่เป็นไฟล์ดิจิทัล — ได้ฟรี แต่ต้องตรวจก่อนเชื่อ
  2. คนพิมพ์เองผ่านหน้าเว็บ — สำหรับไฟล์ที่เป็นภาพสแกนล้วน

ความเสี่ยงใหญ่ที่สุดของทางที่ 1 คือ "ลายน้ำ" ถูกฝังเป็นข้อความด้วย
ถ้าไม่กรองออก มันจะปนเข้าไปในเฉลยแล้วลงโทษ engine ที่อ่านถูก
ตัวกรองด้านล่างจับข้อความที่โผล่ซ้ำแทบทุกหน้า ซึ่งเป็นลายเซ็นของลายน้ำ
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .config import SOURCE_DIR, TRUTH_DIR, ensure_dirs
from .render import doc_id_for


@dataclass
class TruthPage:
    page_id: str
    lines: list[str]
    source: str  # "text_layer" หรือ "manual"
    reviewed: bool = False  # คนตรวจแล้วหรือยัง

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


_SARA_AA = "า"
_SARA_AM = "ำ"
_AM_PLACEHOLDER = ""  # เขตใช้ส่วนตัวของ Unicode จึงไม่ชนกับข้อความจริง


def repair_sara(text: str) -> str:
    """ซ่อมสระที่ถูกแมปผิดใน PDF ที่สร้างจาก Word + THSarabunPSK

    ตรวจแล้วพบว่าไฟล์กฎหมายที่ดินไม่มีสระอา (า) เหลืออยู่เลยแม้แต่ตัวเดียว
    ทุกตัวถูกดึงออกมาเป็นสระอำ (ำ) ส่วนสระอำตัวจริงจะมีช่องว่างนำหน้าเสมอ

        ' ำ'  ช่องว่าง + สระอำ  =  สระอำ ตัวจริง
        'ำ'   เดี่ยว ๆ          =  สระอา ที่ถูกแมปผิด

    ลำดับสำคัญ: ต้องกันตัวจริงไว้ก่อน แล้วค่อยแปลงตัวที่เหลือ

        'ส ำนักงำนคณะกรรมกำรกฤษฎีกำ'  ->  'สำนักงานคณะกรรมการกฤษฎีกา'

    ปลอดภัยเพราะภาษาไทยไม่มีคำที่ขึ้นต้นด้วยสระอา ช่องว่างหน้า 'ำ'
    จึงไม่มีทางเป็นสระอาที่ถูกต้องอยู่แล้ว
    """
    text = text.replace(" " + _SARA_AM, _AM_PLACEHOLDER)
    text = text.replace(_SARA_AM, _SARA_AA)
    return text.replace(_AM_PLACEHOLDER, _SARA_AM)


def needs_sara_repair(text: str) -> bool:
    """เดาว่าข้อความนี้เจอปัญหาการแมปสระหรือไม่

    ข้อความไทยปกติมีสระอามากกว่าสระอำหลายเท่า ถ้าไม่มีสระอาเลยทั้งที่มีสระอำ
    แปลว่าเกือบแน่ว่าโดนแมปผิด
    """
    return _SARA_AM in text and _SARA_AA not in text


def _clean_lines(raw: str) -> list[str]:
    if needs_sara_repair(raw):
        raw = repair_sara(raw)
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def find_repeating_lines(pages: dict[str, list[str]], threshold: float = 0.8) -> set[str]:
    """หาบรรทัดที่โผล่ซ้ำในสัดส่วนหน้ามากผิดปกติ — เกือบแน่ว่าเป็นลายน้ำหรือหัว/ท้ายกระดาษ

    ตั้ง threshold ไว้สูง (80% ของหน้า) เพื่อไม่เผลอตัดเนื้อหาจริงที่บังเอิญซ้ำ
    """
    if not pages:
        return set()
    counter: Counter[str] = Counter()
    for lines in pages.values():
        counter.update(set(lines))  # นับหน้าละครั้งเดียว
    limit = max(2, int(len(pages) * threshold))
    return {line for line, n in counter.items() if n >= limit}


# ตัวยกมีฟอนต์เล็กกว่าตัวปกติในบรรทัดเดียวกันอย่างชัดเจน
# วัดจากเอกสารจริง: ตัวปกติ 15.96 ตัวยก 10.56 = 0.66 เท่า
SUPERSCRIPT_SIZE_RATIO = 0.80
# และ baseline ลอยสูงกว่า (ค่า y น้อยกว่า เพราะแกน y ของ PDF นับลงล่าง)
SUPERSCRIPT_RISE_PT = 1.5


def page_lines_without_superscripts(page) -> list[str]:
    """ข้อความรายบรรทัดโดยตัดตัวยกออก

    ทำไมต้องตัด — เลขเชิงอรรถในกฎหมายไทยเป็นตัวยกต่อท้ายเลขมาตรา
    get_text("text") คืนมาเป็นข้อความไหลเดียวกัน "มาตรา ๑๔" + ตัวยก "๑๓"
    จึงกลายเป็น "มาตรา ๑๔๑๓" ซึ่งไม่มีอยู่จริงในเอกสาร
    เมื่อเอาไปเป็นเฉลย engine ที่อ่านถูกจะถูกนับว่าผิดทุกครั้งที่เจอเลขมาตรา
    (พบกับประมวลกฎหมายที่ดิน 54 หน้า มีจุดแบบนี้หลายสิบจุด)

    แยกออกได้แน่นอนเพราะ PDF เก็บตัวยกเป็น span ต่างหากที่ฟอนต์เล็กกว่า
    และ baseline สูงกว่า จึงไม่ต้องเดาว่าเลขไหนเป็นเลขมาตราเลขไหนเป็นเชิงอรรถ
    """
    out: list[str] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            # เทียบกับขนาดที่ใหญ่ที่สุดในบรรทัด ซึ่งคือขนาดของเนื้อความ
            body = max(s["size"] for s in spans)
            base = max(s["origin"][1] for s in spans)
            kept = [
                s["text"]
                for s in spans
                if not (
                    s["size"] < body * SUPERSCRIPT_SIZE_RATIO
                    and base - s["origin"][1] > SUPERSCRIPT_RISE_PT
                )
            ]
            text = "".join(kept).strip()
            if text:
                out.append(text)
    return out


# อักขระ ASCII ที่แทรกอยู่กลางคำไทย = ฟอนต์ใน PDF แมปผิด
# ข้อความไทยที่ถูกต้องไม่มีทางมี = < > * @ ^ ~ ` | หรือเลขอารบิก คั่นกลางสองพยัญชนะ
_BROKEN_GLYPH = re.compile(r"[ก-๛][=<>*@^~`|0-9][ก-๛]")
# วัดจากเอกสารจริง: ไฟล์ดี 0.00 ต่อพันตัวไทย ไฟล์ที่ฟอนต์เสีย 19.28
BROKEN_PER_1000 = 2.0


def broken_glyph_rate(text: str) -> float:
    """จำนวนอักขระแปลกที่แทรกกลางคำไทย ต่อตัวอักษรไทยหนึ่งพันตัว

    ใช้ตัดสินว่า text layer ของ PDF เชื่อถือได้ไหมก่อนเอาไปเป็นเฉลย

    ที่มา: พบไฟล์รายงานวิจัยที่ text layer มีฟอนต์แมปผิด สระกับวรรณยุกต์
    ออกมาเป็นสัญลักษณ์ 'ชื=อโครงการ' ควรเป็น 'ชื่อโครงการ'
    ถ้าปล่อยเข้าไปเป็นเฉลย ทุก engine จะถูกวัดกับข้อความที่ผิด
    แล้วได้คะแนนต่ำทั้งที่อ่านถูก
    """
    thai = sum(1 for ch in text if "ก" <= ch <= "๛")
    if not thai:
        return 0.0
    return len(_BROKEN_GLYPH.findall(text)) / thai * 1000


def extract_text_layer(
    pdf_path: Path, *, drop_repeating: bool = True
) -> tuple[dict[str, TruthPage], set[str]]:
    """ดึงเฉลยจาก text layer ของ PDF หนึ่งไฟล์

    คืน (เฉลยรายหน้า, บรรทัดที่ถูกกรองออก) เพื่อให้คนตรวจได้ว่ากรองถูกไหม
    """
    doc_id = doc_id_for(pdf_path)
    raw_pages: dict[str, list[str]] = {}

    # ตั้งใจใช้ get_text("text") ที่รวมตัวยกไว้ในบรรทัดตามเดิม ไม่ตัดออก
    #
    # เคยลองตัดตัวยกออกแล้วพบว่าแย่ลง — เลขเชิงอรรถในกฎหมายไทยพิมพ์ติดกับ
    # เลขมาตรา OCR ทุกตัวที่อ่านหน้านั้นถูกจึงได้ "มาตรา ๑๔๑๓" เหมือนกันหมด
    # (ยืนยันกับ typhoon-api-num และ tesseract-tha) การตัดออกจากเฉลยฝ่ายเดียว
    # ทำให้สองฝั่งใช้กติกาคนละแบบ วัดแล้ว CER ของ Typhoon แย่ลงจาก 0.08%
    # เป็น 0.252% ทั้งที่ไม่มีอะไรในตัว engine เปลี่ยน
    #
    # ถ้าต้องการเลขมาตราที่แยกจากเชิงอรรถ (เช่นตัวตรวจลำดับมาตรา)
    # ให้ใช้ page_lines_without_superscripts() แยกต่างหาก อย่าเปลี่ยนเฉลย
    with pymupdf.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            raw_pages[f"{doc_id}_p{idx:03d}"] = _clean_lines(page.get_text("text"))

    dropped = find_repeating_lines(raw_pages) if drop_repeating else set()

    result: dict[str, TruthPage] = {}
    for page_id, lines in raw_pages.items():
        kept = [ln for ln in lines if ln not in dropped]
        result[page_id] = TruthPage(page_id=page_id, lines=kept, source="text_layer")
    return result, dropped


def build_from_sources(source_dir: Path | None = None) -> dict[str, TruthPage]:
    """ดึงเฉลยจากทุก PDF ที่มี text layer แล้วเก็บลงดิสก์"""
    ensure_dirs()
    source_dir = source_dir or SOURCE_DIR
    everything: dict[str, TruthPage] = {}
    skipped: list[tuple[str, float, int]] = []

    for pdf_path in sorted(source_dir.glob("*.pdf")):
        with pymupdf.open(pdf_path) as doc:
            has_text = any(page.get_text("text").strip() for page in doc)
        if not has_text:
            continue

        pages, dropped = extract_text_layer(pdf_path)

        # ไม่รับ text layer ที่ฟอนต์แมปผิด ยอมไม่มีเฉลยดีกว่ามีเฉลยที่ผิด
        # เพราะเฉลยผิดจะลงโทษ engine ที่อ่านถูกโดยไม่มีอะไรฟ้อง
        rate = broken_glyph_rate("\n".join(p.text for p in pages.values()))
        if rate >= BROKEN_PER_1000:
            skipped.append((pdf_path.stem, rate, len(pages)))
            continue

        everything.update(pages)

        report = TRUTH_DIR / f"{doc_id_for(pdf_path)}_dropped.json"
        report.write_text(
            json.dumps(sorted(dropped), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # เก็บเฉลยที่คนพิมพ์เองไว้ ไม่ให้ถูกลบตอนดึงใหม่จาก text layer
    for page_id, page in load().items():
        if page.source != "text_layer":
            everything[page_id] = page

    if skipped:
        print("ข้าม text layer ที่ฟอนต์แมปผิด (ยอมไม่มีเฉลยดีกว่าเฉลยผิด)")
        for name, rate, n in skipped:
            print(f"  {name}  {n} หน้า  อักขระแปลกกลางคำ {rate:.1f} ต่อพันตัว")

    save(everything)
    return everything


def save(pages: dict[str, TruthPage]) -> None:
    ensure_dirs()
    payload = {
        page_id: {"lines": p.lines, "source": p.source, "reviewed": p.reviewed}
        for page_id, p in pages.items()
    }
    (TRUTH_DIR / "truth.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load() -> dict[str, TruthPage]:
    path = TRUTH_DIR / "truth.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        page_id: TruthPage(
            page_id=page_id,
            lines=v["lines"],
            source=v.get("source", "manual"),
            reviewed=v.get("reviewed", False),
        )
        for page_id, v in raw.items()
    }


def upsert(page_id: str, lines: list[str], *, source: str = "manual", reviewed: bool = True) -> None:
    """บันทึกเฉลยของหน้าเดียว เรียกจากหน้าเว็บตอนคนแก้เสร็จ"""
    pages = load()
    pages[page_id] = TruthPage(page_id=page_id, lines=lines, source=source, reviewed=reviewed)
    save(pages)
