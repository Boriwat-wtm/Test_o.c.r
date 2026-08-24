"""หาจุดที่ OCR น่าจะอ่านผิด โดยไม่ต้องมีเฉลย

ทำไมต้องมีโมดูลนี้ทั้งที่มีเฉลยอยู่แล้ว
  เฉลยมีแค่ ๕๔ หน้าจาก ๖๖ หน้า และเอกสารชุดหน้าจะไม่มีเฉลยเลย
  ถ้าตรวจได้เฉพาะตอนมีเฉลย เครื่องมือนี้ก็ใช้กับงานจริงไม่ได้

สองชั้น เรียงตามความเสี่ยงจากน้อยไปมาก
  ชั้นกฎตายตัว   ตัดสินได้โดยไม่ต้องตีความ — เลขยกกำลัง เลขอารบิกในเอกสารเลขไทย
  ชั้นโหวต       engine คนละตระกูลตั้งแต่สองตัวขึ้นไปอ่านได้ไม่ตรงกับตัวนี้

วัดจริงกับ ๑๒ หน้า (๓๗๒ บรรทัด ผิดจริง ๑๔ บรรทัด)

  engine                จับได้     เตือนผิด   ต้องตรวจ
  typhoon-api-num        ๙/๑๔        ๑๒        ๕.๖%
  paddle-th            ๔๙/๖๙          ๖       ๒๒.๐%
  tesseract-tha      ๑๒๑/๑๕๒          ๒       ๓๔.๔%
  easyocr-th         ๑๗๗/๒๑๐          ๗       ๕๑.๗%

สัดส่วนที่ต้องตรวจแปรตามความแม่นของ engine ตามที่ควรเป็น
ตัวที่อ่านผิดเยอะย่อมมีจุดน่าสงสัยเยอะ ไม่ใช่ข้อบกพร่องของตัวคัด

ที่ลองแล้วไม่ผ่าน จึงไม่อยู่ในไฟล์นี้
  - ตรวจด้วยพจนานุกรมไทย (PyThaiNLP newmm)
    ไทยไม่เว้นวรรคระหว่างคำ พอ OCR อ่านผิดมักได้คำที่มีจริงแต่แบ่งคนละแบบ
    'มาตรา' -> 'มา'+'รา'  และ  'กรรมสิทธิ์' -> 'กรรม'+'สิทธิ'  ทุกชิ้นเป็นคำจริง
    วัดทั้งชุดแล้วเตือนผิด ๗ จับได้ ๑ — แย่กว่าไม่ทำ
  - โหวตข้ามเครื่องระดับบรรทัด
    ผิดตัวเดียวในบรรทัดยาว ๙๐ ตัว ค่าความคล้ายแทบไม่ขยับ จับได้ ๐ จาก ๑๔
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

from .metrics import index_map
from .thai_text import THAI_DIGITS, normalize

Box = tuple[int, int, int, int]

# ── ชั้นที่ ๐ : กฎตายตัว ────────────────────────────────────────────────

_SUPERSCRIPT = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUP_TO_THAI = str.maketrans(_SUPERSCRIPT, THAI_DIGITS)
_ARABIC_TO_THAI = str.maketrans("0123456789", THAI_DIGITS)

_SUP_RUN = re.compile(f"[{_SUPERSCRIPT}]+")
_ARABIC_RUN = re.compile(r"[0-9]+")


def thai_digit_document(lines: list[str], ratio: float = 4.0) -> bool:
    """เอกสารนี้ใช้เลขไทยเป็นหลักหรือไม่

    ต้องรู้ก่อนจึงจะบอกได้ว่าเลขอารบิกที่โผล่มาคือของแปลกปลอม
    ถ้าเอกสารใช้เลขอารบิกอยู่แล้ว การไปเตือนทุกตัวเลขจะกลายเป็นเสียงรบกวน
    """
    text = "".join(lines)
    thai = sum(text.count(d) for d in THAI_DIGITS)
    arabic = sum(text.count(d) for d in "0123456789")
    return thai >= 10 and thai > arabic * ratio


def rule_findings(line: str, *, thai_doc: bool) -> list[tuple[int, int, str, str]]:
    """หาจุดที่กฎตายตัวจับได้ในบรรทัดเดียว

    คืนรายการ (เริ่ม, จบ, สิ่งที่ควรเป็น, เหตุผล)

    กฎทั้งหมดในนี้ต้องเป็นเรื่องที่ตัดสินได้โดยไม่ต้องอ่านความหมาย
    ถ้าเริ่มต้องเดาว่าประโยคนี้ควรพูดว่าอะไร แปลว่าไม่ใช่ที่ของกฎ ให้ไปอยู่ชั้นอื่น
    """
    out: list[tuple[int, int, str, str]] = []

    # เลขยกกำลัง: Typhoon อ่านเลขเชิงอรรถที่เป็นเลขไทยยกกำลังออกมาเป็น ¹⁰
    # ค่าถูกแต่เสียความเป็นเลขไทย ซึ่งเป็นสิ่งที่งานนี้วัดโดยตรง
    for m in _SUP_RUN.finditer(line):
        out.append((m.start(), m.end(), m.group().translate(_SUP_TO_THAI),
                    "เลขยกกำลัง — ควรเป็นเลขไทย"))

    # เลขอารบิกในเอกสารที่ใช้เลขไทยล้วน
    if thai_doc:
        for m in _ARABIC_RUN.finditer(line):
            out.append((m.start(), m.end(), m.group().translate(_ARABIC_TO_THAI),
                        "เลขอารบิกในเอกสารเลขไทย"))
    return out


_SECTION_NUM = re.compile(r"มาตรา\s*([๐-๙]+)")


def section_length_outliers(
    lines: list[str], *, min_samples: int = 3, extra_digits: int = 2
) -> dict[int, list[tuple[int, int, str, str]]]:
    """เลขมาตราที่ยาวผิดปกติเทียบกับเลขมาตราอื่นในหน้าเดียวกัน — กฎตายตัวเช่นกัน
    แต่ต้องดูทั้งหน้าพร้อมกัน ไม่ใช่ทีละบรรทัดแบบ rule_findings จึงแยกมาต่างหาก

    วัดจริงพบว่า Typhoon เอาเลขเชิงอรรถตัวยกมาต่อท้ายเลขมาตราแบบไม่มีช่องว่าง
        มาตรา ๑๔ + เชิงอรรถ ๑๓  →  "มาตรา ๑๔๑๓"   (พบ ๓๒ จุดในเอกสารทดสอบ)
    ผลคือค่าถูกทุกตัวแยกกัน แต่ต่อกันแล้วกลายเป็นเลขมาตราที่ไม่มีจริง อ่านเผิน ๆ
    ดูสมเหตุสมผล (ยังเป็นตัวเลข ยังตามหลังคำว่า "มาตรา") จึงเป็นความผิดแบบเนียน
    ที่ชั้นกฎในบรรทัดเดียวจับไม่ได้ และโหวตข้ามเครื่องก็จับไม่ได้เช่นกันถ้า
    engine อื่นอ่านเลขไทยผิดพอ ๆ กันอยู่แล้ว (วัดไว้ก่อนหน้านี้ว่าช่วยได้แค่ 14%)

    ใช้เลขตายตัวเป็นเกณฑ์ไม่ได้ (เช่น "เกิน ๑๑๓") เพราะกฎหมายแต่ละฉบับมีจำนวน
    มาตราไม่เท่ากัน จะใช้ได้แค่ฉบับเดียว จึงเทียบกับ "ความยาวหลักที่พบบ่อยที่สุด
    ในหน้านั้นเอง" (ฐานนิยม) แทน — เป็นเกณฑ์ที่ใช้ข้ามเอกสารได้จริง

    ต้องมีเลขมาตราอย่างน้อย min_samples ค่าในหน้า ถึงจะคำนวณฐานนิยมได้น่าเชื่อถือ
    หน้าที่มีมาตราแค่หนึ่งสองค่าไม่พอตัดสิน ปล่อยผ่านดีกว่าเดามั่ว
    """
    hits: list[tuple[int, int, int, str]] = []  # (บรรทัด, เริ่ม, จบ, ตัวเลข)
    for i, line in enumerate(lines):
        for m in _SECTION_NUM.finditer(line):
            hits.append((i, m.start(1), m.end(1), m.group(1)))

    if len(hits) < min_samples:
        return {}

    mode_len = Counter(len(d) for _, _, _, d in hits).most_common(1)[0][0]

    out: dict[int, list[tuple[int, int, str, str]]] = {}
    for line_idx, start, end, digits in hits:
        if len(digits) < mode_len + extra_digits:
            continue
        # เดาว่าส่วนท้ายที่เกินมาคือเลขเชิงอรรถที่ต่อเข้ามา ตัดกลับเหลือความยาวปกติ
        guess = digits[:mode_len]
        out.setdefault(line_idx, []).append((
            start, end, guess,
            f"เลขมาตรายาว {len(digits)} หลัก ทั้งที่ส่วนใหญ่ในเอกสารนี้ยาว {mode_len} หลัก "
            "— น่าจะมีเลขเชิงอรรถต่อท้ายมา",
        ))
    return out


def section_findings_by_document(
    pages: dict[str, list[str]],
) -> dict[str, dict[int, list[tuple[int, int, str, str]]]]:
    """หา section_length_outliers ของหลายหน้าที่เป็นเอกสารเดียวกัน โดยคำนวณ
    ฐานนิยมจากเลขมาตราทั้งเอกสารรวมกัน ไม่ใช่ทีละหน้า

    ทำไมต้องรวมก่อน — วัดจริงพบว่าคำนวณฐานนิยมทีละหน้า (ที่ scan_page ทำอยู่
    เดิม) จับได้แค่ 4 จุด จาก 32 จุดที่มีจริง เพราะหน้าเดียวมักมีเลขมาตราแค่
    2-4 ค่า ไม่พอตั้งฐานนิยมให้น่าเชื่อถือ (min_samples ของ
    section_length_outliers กันไว้ไม่ให้เดาจากตัวอย่างน้อยเกินไปอยู่แล้ว)
    พอรวมทั้งเอกสาร (ทุกหน้าของ เอกสารเดียวกัน มีเลขมาตราเรียงต่อเนื่องกัน
    อยู่แล้วตามธรรมชาติของกฎหมาย) จับได้ครบ 32/32

    pages ต้องเป็นหน้าของเอกสารเดียวกันเท่านั้น (ผู้เรียกเป็นคนแบ่งตาม
    doc_id เอง เพราะโมดูลนี้ไม่รู้จักโครงสร้างเอกสาร เป็นเรื่องของ render.py)
    คืนค่าแยกกลับเป็นรายหน้าเพื่อให้ส่งเข้า scan_page(extra_findings=...) ได้ตรง
    """
    flat: list[tuple[str, int]] = []  # (page_id, ดัชนีบรรทัดในหน้านั้น)
    all_lines: list[str] = []
    for pid, lines in pages.items():
        for i, ln in enumerate(lines):
            flat.append((pid, i))
            all_lines.append(ln)

    out: dict[str, dict[int, list[tuple[int, int, str, str]]]] = {}
    for flat_idx, items in section_length_outliers(all_lines).items():
        pid, line_idx = flat[flat_idx]
        out.setdefault(pid, {}).setdefault(line_idx, []).extend(items)
    return out


def section_suspects(
    page_id: str,
    engine: str,
    lines: list[str],
    findings: dict[int, list[tuple[int, int, str, str]]],
) -> list[Suspect]:
    """แปลงผลของ section_findings_by_document ให้เป็น Suspect สำหรับหน้าเว็บ

    ไม่มีกล่องให้เลย (box=None) เพราะ findings มาจากบรรทัดดิบของ engine เอง
    ไม่ได้ผ่านกริดที่คู่กับพิกัดภาพ (เหตุผลเดียวกับที่ scan_page ไม่รวมกฎนี้
    ไว้ในตัว) หน้าเว็บจะแสดงได้แต่ไม่มีภาพครอปให้จุดพวกนี้ ยังดีกว่าไม่แสดงเลย
    """
    out: list[Suspect] = []
    for line_idx, items in findings.items():
        if line_idx >= len(lines):
            continue
        text = lines[line_idx]
        out.append(Suspect(
            page_id=page_id,
            engine=engine,
            grid_line=line_idx,
            text=text,
            findings=[
                Finding(s, e, text[s:e], fix, why, "rule") for s, e, fix, why in items
            ],
        ))
    return out


# ── ชั้นที่ ๒ : โหวตข้ามเครื่องระดับตัวอักษร ───────────────────────────

def cross_engine_findings(
    line: str,
    peers: list[str],
    *,
    min_votes: int = 2,
) -> list[tuple[int, int, str, str]]:
    """หาช่วงที่ engine อื่นตั้งแต่สองตัวขึ้นไปเห็นตรงกันว่าควรเป็นอย่างอื่น

    ต้องเทียบระดับตัวอักษร ไม่ใช่ระดับบรรทัด
    วัดแล้ว: เทียบทั้งบรรทัดจับได้ ๐ จาก ๑๔ เพราะผิดตัวเดียวในบรรทัด ๙๐ ตัว
    ค่าความคล้ายขยับไม่ถึง ๒% ซึ่งจมอยู่ในความต่างปกติระหว่าง engine

    ใช้ opcodes ของ Levenshtein แทนที่จะเทียบตำแหน่งตรง ๆ
    เพราะแต่ละ engine ใส่ช่องว่างและตกหล่นไม่เท่ากัน ตำแหน่งจึงเลื่อนกันเสมอ
    """
    if len(peers) < min_votes:
        return []

    votes: Counter[tuple[int, int, str]] = Counter()
    for peer in peers:
        for op in Levenshtein.opcodes(line, peer):
            if op.tag != "equal":
                votes[(op.src_start, op.src_end, peer[op.dest_start:op.dest_end])] += 1

    return [
        (start, end, says, f"engine อื่น {n} ตัวอ่านได้เป็นอย่างอื่น")
        for (start, end, says), n in votes.items()
        if n >= min_votes
    ]


# ── รวมผลของทุกชั้น ────────────────────────────────────────────────────

@dataclass
class Finding:
    """จุดเดียวที่น่าสงสัย ภายในบรรทัดหนึ่ง"""

    start: int
    end: int
    text: str  # สิ่งที่ engine อ่านได้ตรงช่วงนี้
    suggestion: str  # สิ่งที่กฎหรือเสียงข้างมากบอกว่าควรเป็น
    reason: str
    layer: str  # "rule" หรือ "vote"


@dataclass
class Suspect:
    """บรรทัดหนึ่งที่มีจุดน่าสงสัยอย่างน้อยหนึ่งจุด"""

    page_id: str
    engine: str
    # ดัชนีบน "กริด" ไม่ใช่ดัชนีในผลของ engine ตัวนี้ — สองอย่างนี้ไม่ตรงกัน
    # VLM รวมย่อหน้าเป็นบรรทัดเดียว เลขบรรทัดของมันจึงคนละระบบกับบรรทัดในภาพ
    # ห้ามเอาไปเขียนทับ lines[grid_line] ของ engine เด็ดขาด จะทับผิดบรรทัด
    # ถ้าจะแก้ผลกลับ ให้แทนที่ด้วยข้อความ (text) ไม่ใช่ด้วยดัชนี
    grid_line: int
    # ส่วนของบรรทัดในภาพนี้ ตามที่ engine เป้าหมายอ่านได้
    text: str
    findings: list[Finding] = field(default_factory=list)
    # พิกัดบนภาพ ยืมมาจาก engine อื่นได้ถ้าตัวนี้ไม่คืนพิกัด
    box: Box | None = None
    box_from: str | None = None

    @property
    def layers(self) -> set[str]:
        return {f.layer for f in self.findings}


def find_in_line(
    line: str,
    peers: list[str],
    *,
    thai_doc: bool,
) -> list[Finding]:
    """รันทุกชั้นกับบรรทัดเดียว แล้วคืนจุดน่าสงสัยทั้งหมด"""
    found: list[Finding] = []

    for start, end, fix, why in rule_findings(line, thai_doc=thai_doc):
        found.append(Finding(start, end, line[start:end], fix, why, "rule"))

    # ชั้นโหวตต้องเทียบบนข้อความที่จัดรูปแล้ว ไม่งั้นความต่างที่ไม่ใช่การอ่านผิด
    # (ช่องว่าง ลำดับวรรณยุกต์ สระอำที่เขียนแยกส่วน) จะกลายเป็นเสียงเตือนปลอม
    # แต่ตำแหน่งที่ได้เป็นของข้อความหลังจัดรูป ต้องแปลงกลับเป็นตำแหน่งจริง
    # ก่อนเอาไปไฮไลต์บนหน้าเว็บ ไม่งั้นขีดเส้นใต้ผิดตัว
    dense = normalize(line)
    dense_peers = [n for p in peers if (n := normalize(p))]
    back = index_map(dense, line)

    for start, end, says, why in cross_engine_findings(dense, dense_peers):
        real_start, real_end = back[start], back[min(end, len(dense))]
        if real_end <= real_start:
            real_end = min(real_start + 1, len(line))
        found.append(
            Finding(real_start, real_end, line[real_start:real_end], says, why, "vote")
        )

    return sorted(found, key=lambda f: (f.start, f.end))


def engine_family(name: str) -> str:
    """ชื่อตระกูลของ engine — ส่วนหน้าสุดก่อนขีดแรก

    typhoon-api, typhoon-api-num, typhoon-2b ล้วนเป็นโมเดลเดียวกัน
    ต่างกันแค่คำสั่งหรือวิธีเรียก จึงอ่านผิดแบบเดียวกัน
    ถ้าปล่อยให้โหวตกันเองจะได้สองเสียงจากความเห็นเดียว
    """
    return name.split("+")[0].split("-")[0]


def engine_variant(name: str) -> str:
    """อ่านจากภาพชุดไหน — ลบลายน้ำแล้วหรือภาพดิบ"""
    return "clean" if name.endswith("+clean") else "raw"


def independent_peers(target: str, names: list[str]) -> list[str]:
    """คัดเฉพาะ engine ที่ให้ความเห็นอิสระจริงกับตัวเป้าหมาย

    ตัดสองกลุ่มออก
      1. ตระกูลเดียวกัน — อ่านผิดเหมือนกันอยู่แล้ว ไม่ใช่ความเห็นที่สอง
      2. คนละชุดภาพ — ตัวที่อ่านภาพดิบเห็นลายน้ำด้วย ข้อความจึงต่างกัน
         โดยไม่เกี่ยวกับความแม่น ถ้าเอามาโหวตจะได้แต่เสียงเตือนปลอม
    """
    family, variant = engine_family(target), engine_variant(target)
    picked: dict[str, str] = {}
    for n in sorted(names):
        fam = engine_family(n)
        if n == target or fam == family or engine_variant(n) != variant:
            continue
        # หนึ่งเสียงต่อหนึ่งตระกูล — ถ้านับ typhoon-api กับ typhoon-api-num
        # เป็นสองเสียง เกณฑ์ "สองตัวเห็นตรงกัน" จะผ่านได้ด้วยความเห็นเดียว
        picked.setdefault(fam, n)
    return list(picked.values())


def pick_grid(pages: dict[str, tuple[list[str], list[list[int] | None]]]) -> str | None:
    """เลือก engine ที่จะใช้เป็น "แกนบรรทัด" ของหน้า

    ทุกตัวต้องมาเทียบกันบนกริดเดียว ไม่งั้นเทียบไม่ได้เลย เพราะ
      - VLM รวมย่อหน้าที่ถูกตัดคำให้เป็นบรรทัดเดียว
      - PaddleOCR กับ EasyOCR ซอยบรรทัดเดียวเป็นชิ้นย่อย
    จับคู่สองแบบนี้ตรง ๆ แล้วจะได้เสียงเตือนปลอมท่วม (วัดแล้ว ๑๐๖ จาก ๓๕๘ บรรทัด)

    แกนต้องมาจากตัวที่ซอยตามบรรทัดจริงในภาพและคืนพิกัดมาด้วย
    จึงเลือกตัวที่ให้บรรทัดน้อยที่สุดในบรรดาตัวที่มีพิกัด เพราะความผิดพลาด
    ที่เจอจริงคือการซอยเกิน ไม่ใช่ซอยขาด
    (วัดกับ ๖ หน้า: Tesseract ให้ 29/36/29/8/34/32 เทียบกับเฉลย 28/36/29/8/34/32
     ส่วน EasyOCR ให้ถึง 47/57/42/11/77/59)
    """
    candidates = [
        (sum(1 for b in boxes if b), name)
        for name, (lines, boxes) in pages.items()
        if any(boxes) and lines
    ]
    return min(candidates)[1] if candidates else None


@dataclass
class GridLine:
    """หนึ่งบรรทัดบนภาพ พร้อมสิ่งที่แต่ละ engine อ่านได้ตรงบรรทัดนั้น"""

    index: int
    box: Box | None
    reads: dict[str, str] = field(default_factory=dict)


def build_grid(
    pages: dict[str, tuple[list[str], list[list[int] | None]]],
    grid_engine: str,
) -> list[GridLine]:
    """จัดผลของทุก engine ลงบนกริดบรรทัดเดียวกัน"""
    from .metrics import align_lines

    grid_lines, grid_boxes = pages[grid_engine]
    out = [
        GridLine(
            index=i,
            box=tuple(grid_boxes[i]) if i < len(grid_boxes) and grid_boxes[i] else None,  # type: ignore[arg-type]
            reads={grid_engine: line},
        )
        for i, line in enumerate(grid_lines)
    ]

    for name, (lines, _) in pages.items():
        if name == grid_engine:
            continue
        # ใช้กริดเป็นฝั่ง "เฉลย" — align_lines จะหั่นย่อหน้าที่ VLM รวมมา
        # กลับเป็นทีละบรรทัดตามกริดให้เอง
        for pair in align_lines(grid_lines, lines).pairs:
            if pair.truth_index is None or pair.pred_index is None:
                continue
            out[pair.truth_index].reads[name] = pair.pred
    return out


def scan_page(
    page_id: str,
    engine: str,
    pages: dict[str, tuple[list[str], list[list[int] | None]]],
    *,
    thai_doc: bool,
    grid_engine: str | None = None,
) -> list[Suspect]:
    """หาจุดน่าสงสัยของ engine หนึ่งตัวในหน้าหนึ่ง

    pages คือ {ชื่อ engine: (บรรทัด, พิกัด)} ของทุกตัวบนหน้าเดียวกัน รวมตัวเป้าหมาย

    ไม่ใช้เฉลยเลย จึงใช้กับเอกสารที่ยังไม่มีคนทำเฉลยได้ ซึ่งเป็นกรณีของงานจริง

    ตั้งใจไม่รวม section_length_outliers ไว้ในนี้ แม้จะเป็นกฎตายตัวเหมือนกัน
    เพราะกฎนั้นต้องดูบรรทัดดิบของ engine เอง การจัดกริดในนี้ (align_lines
    เทียบกับ grid_engine) มักตัดเลขมาตราที่ต่อกันให้ขาดเป็นคนละแถวกริด จนกฎ
    จับไม่เจอเกือบหมด (วัดแล้ว: ผ่านกริดจับได้ 4/31 จุด ไม่ผ่านกริดจับได้ 31/31)
    ผู้เรียกที่มีบรรทัดดิบทั้งเอกสารอยู่แล้วจึงควรเรียก section_suspects()
    แยกต่างหาก แล้วเอาผลมาต่อกับผลจากฟังก์ชันนี้เอง (ดู app.py._scan_suspects)
    """
    grid_engine = grid_engine or pick_grid(pages)
    if grid_engine is None or engine not in pages:
        return []

    out: list[Suspect] = []
    for row in build_grid(pages, grid_engine):
        mine = row.reads.get(engine, "")
        if not mine.strip():
            continue
        peers = [t for n, t in row.reads.items() if n != engine and t.strip()]
        findings = find_in_line(mine, peers, thai_doc=thai_doc)
        if findings:
            out.append(
                Suspect(
                    page_id=page_id,
                    engine=engine,
                    grid_line=row.index,
                    text=mine,
                    findings=findings,
                    box=row.box,
                    box_from=engine if engine == grid_engine else f"ยืมจาก {grid_engine}",
                )
            )
    return out
