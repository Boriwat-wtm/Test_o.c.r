"""วัดความแม่นของ OCR โดยเทียบกับเฉลย

หลักการ: เทียบทีละตัวอักษรด้วย edit distance แล้วเอา "รอยแก้" ที่ได้ไปใช้ต่อ
ทั้งการคิด CER, ความแม่นรายกลุ่มอักขระ และการไฮไลต์จุดผิดบนหน้าเว็บ
ทุกอย่างจึงมาจากการเทียบครั้งเดียวกัน ตัวเลขกับสีที่เห็นตรงกันเสมอ
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .thai_text import CHAR_CLASSES, classify_char, normalize, thai_to_arabic_digits

SpanKind = Literal["ok", "wrong", "missing"]


@dataclass
class Span:
    """ชิ้นข้อความหนึ่งช่วงพร้อมสถานะ ใช้ระบายสีบนหน้าเว็บ

    ok      = อ่านถูก
    wrong   = อ่านผิด (text คือสิ่งที่ OCR อ่านได้, expected คือเฉลย)
    missing = ตกหล่น  (text คือเฉลยที่ OCR ไม่ได้อ่านออกมาเลย)
    """

    kind: SpanKind
    text: str
    expected: str = ""


@dataclass
class LineScore:
    cer: float
    truth_len: int
    edits: int
    spans: list[Span] = field(default_factory=list)
    correct_by_class: Counter[str] = field(default_factory=Counter)
    total_by_class: Counter[str] = field(default_factory=Counter)
    confusions: Counter[tuple[str, str]] = field(default_factory=Counter)

    def accuracy_by_class(self) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for cls in CHAR_CLASSES:
            total = self.total_by_class[cls]
            out[cls] = (self.correct_by_class[cls] / total) if total else None
        return out


def _merge(spans: list[Span]) -> list[Span]:
    """รวมช่วงที่ติดกันและสถานะเดียวกัน ให้ HTML ที่ออกมาไม่แตกเป็นชิ้นเล็ก ๆ"""
    merged: list[Span] = []
    for s in spans:
        if merged and merged[-1].kind == s.kind:
            merged[-1].text += s.text
            merged[-1].expected += s.expected
        else:
            merged.append(Span(s.kind, s.text, s.expected))
    return merged


def compare(
    truth: str,
    pred: str,
    *,
    keep_spaces: bool = False,
    lenient_digits: bool = False,
) -> LineScore:
    """เทียบเฉลยกับผลของ OCR หนึ่งบรรทัด

    keep_spaces    เก็บช่องว่างไว้ในการเทียบ (ค่าตั้งต้นคือตัดทิ้ง เพราะไทยไม่เว้นวรรคระหว่างคำ)
    lenient_digits แปลงเลขไทยเป็นเลขอารบิกทั้งสองฝั่งก่อนเทียบ — ใช้ตอบว่า "ค่าถูกไหม"
                   ต่างจากค่าตั้งต้นที่ตอบว่า "อ่านเลขไทยออกมาเป็นเลขไทยได้ไหม"
    """
    t = normalize(truth, keep_spaces=keep_spaces)
    p = normalize(pred, keep_spaces=keep_spaces)
    if lenient_digits:
        t = thai_to_arabic_digits(t)
        p = thai_to_arabic_digits(p)

    score = LineScore(cer=0.0, truth_len=len(t), edits=0)

    for ch in t:
        score.total_by_class[classify_char(ch)] += 1

    if not t:
        # ไม่มีเฉลย ทุกอย่างที่ OCR พ่นออกมาคือส่วนเกิน
        score.cer = 1.0 if p else 0.0
        if p:
            score.spans = [Span("wrong", p)]
        return score

    edits = 0
    spans: list[Span] = []

    for op, t0, t1, p0, p1 in Levenshtein.opcodes(t, p):
        t_seg, p_seg = t[t0:t1], p[p0:p1]

        if op == "equal":
            spans.append(Span("ok", p_seg))
            for ch in t_seg:
                score.correct_by_class[classify_char(ch)] += 1

        elif op == "replace":
            edits += max(len(t_seg), len(p_seg))
            spans.append(Span("wrong", p_seg, t_seg))
            if len(t_seg) == len(p_seg):
                for a, b in zip(t_seg, p_seg):
                    score.confusions[(a, b)] += 1

        elif op == "delete":  # เฉลยมี แต่ OCR ไม่ได้อ่านออกมา
            edits += len(t_seg)
            spans.append(Span("missing", t_seg, t_seg))

        elif op == "insert":  # OCR พ่นเกินมา
            edits += len(p_seg)
            spans.append(Span("wrong", p_seg))

    score.edits = edits
    score.cer = edits / len(t)
    score.spans = _merge(spans)
    return score


@dataclass
class LinePair:
    """คู่ระหว่างบรรทัดในเฉลยกับบรรทัดที่ OCR อ่านได้

    truth_index เป็น None  = OCR พ่นบรรทัดนี้เกินมา ไม่มีในเฉลย (ลายน้ำ ลายเซ็น ขยะ)
    pred_index เป็น None   = OCR ไม่ได้อ่านบรรทัดนี้เลย
    """

    truth_index: int | None
    pred_index: int | None
    truth: str
    pred: str
    score: LineScore | None = None


@dataclass
class PageScore:
    pairs: list[LinePair] = field(default_factory=list)
    matched: list[LineScore] = field(default_factory=list)
    spurious_lines: int = 0
    spurious_chars: int = 0
    missed_lines: int = 0
    missed_chars: int = 0
    truth_lines: int = 0

    @property
    def matched_cer(self) -> float | None:
        """ความผิดของตัวอักษรเฉพาะบรรทัดที่จับคู่ได้ — วัด 'อ่านแม่นแค่ไหน'"""
        total = sum(s.truth_len for s in self.matched)
        return sum(s.edits for s in self.matched) / total if total else None

    @property
    def recall(self) -> float | None:
        """สัดส่วนบรรทัดในเฉลยที่ OCR หาเจอ — วัด 'อ่านครบแค่ไหน'"""
        if not self.truth_lines:
            return None
        return (self.truth_lines - self.missed_lines) / self.truth_lines


def _index_map(src: str, dest: str) -> list[int]:
    """ตารางแปลงตำแหน่งในสตริงหนึ่งไปเป็นตำแหน่งในอีกสตริง (ยาว len(src)+1)

    ใช้ opcodes ของ Levenshtein เป็นโครง แล้วเกลี่ยตำแหน่งภายในแต่ละช่วงตามสัดส่วน
    ไม่ต้องแม่นระดับตัวอักษร เพราะเอาไปใช้หาจุด "ตัดบรรทัด" เท่านั้น
    คลาดไปหนึ่งสองตัวก็ยังตัดถูกที่ และคะแนนจริงคำนวณใหม่จากข้อความดิบอยู่ดี
    """
    table = [0] * (len(src) + 1)
    for op in Levenshtein.opcodes(src, dest):
        span_src = op.src_end - op.src_start
        span_dest = op.dest_end - op.dest_start
        for k in range(op.src_start, op.src_end):
            offset = k - op.src_start
            shift = round(offset * span_dest / span_src) if span_src else 0
            table[k] = op.dest_start + shift
        table[op.src_end] = op.dest_end
    table[len(src)] = len(dest)
    return table


def split_by_truth(truth_group: list[str], pred: str) -> list[str]:
    """หั่นบรรทัดเดียวของ OCR กลับเป็นหลายท่อน ให้ตรงกับบรรทัดในเฉลย

    VLM คืนย่อหน้าเป็นก้อนเดียว แต่ในภาพมันคือหลายบรรทัด
    ถ้าไม่หั่นกลับ หน้าเว็บจะเทียบก้อนยาวกับบรรทัดสั้นแล้วขึ้นแดงทั้งแถบ
    ทั้งที่อ่านถูกทุกตัว หั่นแล้วผู้ใช้กวาดตาเทียบกับรูปทีละบรรทัดได้เหมือนเดิม
    """
    keep = [k for k, ch in enumerate(pred) if not ch.isspace()]
    dense = "".join(pred[k] for k in keep)
    parts = [normalize(t) for t in truth_group]
    joined = "".join(parts)
    if not joined or not dense:
        return [pred] + [""] * (len(truth_group) - 1)

    table = _index_map(joined, dense)
    cuts = []
    acc = 0
    for part in parts[:-1]:
        acc += len(part)
        dense_pos = table[acc]
        cuts.append(keep[dense_pos] if dense_pos < len(keep) else len(pred))

    out = []
    start = 0
    for cut in [*cuts, len(pred)]:
        cut = max(cut, start)
        out.append(pred[start:cut].strip())
        start = cut
    return out


def _attach_merged_truth(
    norm_truth: list[str],
    norm_pred: list[str],
    matches: dict[int, int],
    used_truth: set[int],
    *,
    min_score: float = 80.0,
) -> dict[int, list[int]]:
    """หาบรรทัดเฉลยที่ไปรวมอยู่ในก้อนเดียวกับบรรทัดอื่นของ OCR

    คืน {ดัชนีบรรทัด OCR: [ดัชนีบรรทัดเฉลยทุกบรรทัดที่ก้อนนั้นครอบคลุม]}

    ทำไมการจับคู่หนึ่งต่อหนึ่งอย่างเดียวไม่พอ
      normalized_similarity หารด้วยความยาวของสตริงที่ยาวกว่า พอ OCR รวมห้าบรรทัด
      เป็นย่อหน้าเดียวยาว ๕๐๐ ตัว เทียบกับเฉลยบรรทัดเดียวยาว ๙๐ ตัว
      ค่าจะตกไปราว ๐.๑๘ ต่ำกว่า threshold ทั้งที่ข้อความอยู่ครบทุกตัว
      บรรทัดพวกนั้นจึงถูกนับว่า "OCR ไม่ได้อ่าน" ซึ่งผิดความจริง

    จึงใช้ partial_ratio แทนสำหรับกรณีนี้ — มันหาช่วงย่อยใน OCR ที่ตรงกับเฉลยที่สุด
    ความยาวส่วนเกินจึงไม่ถูกนำมาหาร ตอบคำถามที่ถูกต้องว่า
    "บรรทัดนี้อยู่ในก้อนนั้นไหม" ไม่ใช่ "สองสตริงนี้เหมือนกันไหม"
    """
    picked: dict[int, int] = {}
    for ti, truth in enumerate(norm_truth):
        if ti in used_truth or not truth:
            continue
        best_pi, best_score = None, min_score
        for pi, pred in enumerate(norm_pred):
            if len(pred) <= len(truth) * 1.3:  # ไม่ใช่ก้อนรวม ข้าม
                continue
            score = fuzz.partial_ratio(truth, pred, score_cutoff=best_score)
            if score > best_score:
                best_pi, best_score = pi, score
        if best_pi is not None:
            picked[ti] = best_pi
            used_truth.add(ti)

    _snap_to_neighbours(picked, matches, norm_truth, norm_pred, min_score)

    extra: dict[int, list[int]] = {}
    for ti, pi in picked.items():
        extra.setdefault(pi, []).append(ti)

    # ดึงบรรทัดที่จับคู่ไว้ตั้งแต่รอบแรกเข้ากลุ่มเดียวกันด้วย
    # ก้อนหนึ่งมักครอบทั้งบรรทัดที่แมตช์แล้วและบรรทัดที่ยังไม่แมตช์ปนกัน
    # ต้องหั่นพร้อมกันทั้งกลุ่ม ไม่งั้นจุดตัดจะเหลื่อม
    for ti, pi in matches.items():
        if pi in extra:
            extra[pi].append(ti)
    return {pi: sorted(set(tis)) for pi, tis in extra.items()}


def _snap_to_neighbours(
    picked: dict[int, int],
    matches: dict[int, int],
    norm_truth: list[str],
    norm_pred: list[str],
    min_score: float,
) -> None:
    """ย้ายบรรทัดที่หลุดไปเกาะก้อนผิด ให้กลับไปอยู่ก้อนเดียวกับบรรทัดข้างเคียง

    partial_ratio มองหาข้อความย่อยที่ไหนก็ได้ในก้อน จุดอ่อนคือบรรทัดสั้น ๆ
    อย่าง "กฎกระทรวง" หรือ "และ" ไปเจอตัวเองในย่อหน้าอื่นที่ไม่เกี่ยวกันแล้วได้ ๑๐๐ เต็ม
    ผลคือหางของย่อหน้าถูกดึงไปคนละที่ แล้วจุดตัดของทั้งกลุ่มเลื่อนตามไปด้วย

    ข้อความที่อยู่ติดกันในเฉลยย่อมอยู่ก้อนเดียวกัน ใช้ข้อเท็จจริงนี้แก้
    ถ้าบรรทัดหนึ่งไปอยู่คนละก้อนกับทั้งบรรทัดบนและล่าง ให้ย้ายไปอยู่กับเพื่อนบ้าน
    เท่าที่คะแนนยังผ่านเกณฑ์เดิม
    """
    where = {**matches, **picked}
    for ti in sorted(picked):
        here = picked[ti]
        around = {where.get(ti - 1), where.get(ti + 1)} - {None, here}
        if not around or here in (where.get(ti - 1), where.get(ti + 1)):
            continue
        best_pi, best_score = None, min_score
        for pi in around:
            score = fuzz.partial_ratio(norm_truth[ti], norm_pred[pi])
            if score > best_score:
                best_pi, best_score = pi, score
        if best_pi is not None:
            picked[ti] = where[ti] = best_pi


def align_lines(
    truth_lines: list[str],
    pred_lines: list[str],
    *,
    threshold: float = 0.45,
) -> PageScore:
    """จับคู่บรรทัดเฉลยกับบรรทัดที่ OCR อ่านได้ ด้วยความคล้ายของข้อความ

    ทำไมต้องจับคู่ทีละบรรทัด ไม่ต่อทั้งหน้าเป็นก้อนเดียว
      1. OCR แต่ละตัวลำดับการอ่านไม่เหมือนกัน ต่อเป็นก้อนแล้วเทียบจะเพี้ยนทั้งที่อ่านถูก
      2. ตัวที่อ่านลายน้ำหรือลายเซ็นเจอ จะถูกลงโทษหนักเกินจริงเพราะมีตัวอักษรเกิน
         ทั้งที่ความผิดจริงคือ "ตรวจเจอสิ่งที่ไม่ควรเจอ" ไม่ใช่ "อ่านตัวอักษรผิด"

    รองรับกรณีจับคู่แบบหลายต่อหนึ่งด้วย เพราะ VLM คืนย่อหน้าเป็นก้อนเดียว
    ไม่แบ่งตามบรรทัดในภาพ ถ้าจับคู่แบบหนึ่งต่อหนึ่งอย่างเดียว ก้อนนั้นจะแมตช์
    เฉลยได้แค่บรรทัดแรก ที่เหลือถูกนับว่า "ไม่ได้อ่าน" ทั้งที่ข้อความอยู่ครบ
    (วัดจริงกับ Typhoon: รายงานว่าอ่านได้ ๙/๓๔ บรรทัด ทั้งที่ CER ทั้งหน้า ๐.๐๔%)

    แยกรายงานสามอย่างจึงตรงกับความจริงกว่า
      matched_cer      อ่านตัวอักษรแม่นแค่ไหน (เฉพาะบรรทัดที่จับคู่ได้)
      recall           อ่านครบแค่ไหน
      spurious_lines   พ่นบรรทัดเกินมาเท่าไร
    """
    norm_truth = [normalize(t) for t in truth_lines]
    norm_pred = [normalize(p) for p in pred_lines]

    candidates: list[tuple[float, int, int]] = []
    for ti, t in enumerate(norm_truth):
        if not t:
            continue
        for pi, p in enumerate(norm_pred):
            if not p:
                continue
            sim = Levenshtein.normalized_similarity(t, p)
            if sim >= threshold:
                candidates.append((sim, ti, pi))

    # จับคู่แบบละโมบจากคู่ที่คล้ายที่สุดลงมา หนึ่งบรรทัดจับคู่ได้ครั้งเดียว
    candidates.sort(reverse=True)
    used_truth: set[int] = set()
    used_pred: set[int] = set()
    matches: dict[int, int] = {}
    for _sim, ti, pi in candidates:
        if ti in used_truth or pi in used_pred:
            continue
        matches[ti] = pi
        used_truth.add(ti)
        used_pred.add(pi)

    groups = _attach_merged_truth(norm_truth, norm_pred, matches, used_truth)

    # หั่นก้อนที่ OCR รวมมา กลับเป็นทีละบรรทัดตามเฉลย
    segments: dict[int, str] = {}
    for pi, members in groups.items():
        # ตรวจทั้งกลุ่มอีกชั้นก่อนเชื่อ: เอาเฉลยทุกบรรทัดในกลุ่มมาต่อกัน
        # แล้วต้องใกล้เคียงกับก้อนของ OCR ทั้งก้อน ไม่ใช่แค่บางช่วง
        #
        # ด่านนี้จำเป็นเพราะ partial_ratio ตอบแค่ว่า "บรรทัดนี้โผล่ในก้อนไหม"
        # ตัวที่แบ่งบรรทัดตามภาพอยู่แล้วอย่าง Tesseract หรือ PaddleOCR
        # อาจมีบรรทัดสั้น ๆ ที่บังเอิญไปโผล่ในก้อนยาวของบรรทัดอื่น
        # ถ้าไม่กันไว้ บรรทัดที่ OCR ไม่ได้อ่านจริงจะถูกนับว่าอ่านได้ ทำให้คะแนนสวยเกินจริง
        joined = "".join(norm_truth[m] for m in members)
        if Levenshtein.normalized_similarity(joined, norm_pred[pi]) < 0.7:
            continue
        used_pred.add(pi)
        pieces = split_by_truth([truth_lines[m] for m in members], pred_lines[pi])
        for ti, piece in zip(members, pieces):
            segments[ti] = piece
            matches[ti] = pi

    page = PageScore(truth_lines=sum(1 for t in norm_truth if t))

    for ti, truth_line in enumerate(truth_lines):
        if not norm_truth[ti]:
            continue
        if ti in matches:
            pi = matches[ti]
            pred_line = segments.get(ti, pred_lines[pi])
            score = compare(truth_line, pred_line)
            page.matched.append(score)
            page.pairs.append(LinePair(ti, pi, truth_line, pred_line, score))
        else:
            page.missed_lines += 1
            page.missed_chars += len(norm_truth[ti])
            page.pairs.append(LinePair(ti, None, truth_line, "", compare(truth_line, "")))

    for pi, pred_line in enumerate(pred_lines):
        if pi in used_pred or not norm_pred[pi]:
            continue
        page.spurious_lines += 1
        page.spurious_chars += len(norm_pred[pi])
        page.pairs.append(LinePair(None, pi, "", pred_line))

    return page


def page_cer(truth_lines: list[str], pred_lines: list[str]) -> float | None:
    """CER ระดับหน้า — ต่อทุกบรรทัดเป็นก้อนเดียวแล้วตัดช่องว่างทิ้งก่อนเทียบ

    มีไว้คู่กับ align_lines() เพราะทั้งสองค่าตอบคำถามต่างกัน

    ค่านี้ไม่สนใจว่าขึ้นบรรทัดตรงไหน จึงเป็นธรรมกับ VLM อย่าง Typhoon
    ที่รวมย่อหน้าเป็นบรรทัดเดียวแทนที่จะแบ่งตามบรรทัดในภาพ
    แต่จะลงโทษหนักถ้าอ่านลายน้ำเจอเป็นร้อยบรรทัด เพราะนับเป็นตัวอักษรเกินทั้งหมด

    ส่วน matched_cer จาก align_lines() ตรงกันข้าม — ทนต่อบรรทัดเกิน
    แต่ลงโทษการรวมบรรทัด รายงานทั้งสองค่าจึงเห็นภาพครบ
    """
    truth_text = "\n".join(truth_lines)
    pred_text = "\n".join(pred_lines)
    if not normalize(truth_text):
        return None
    return compare(truth_text, pred_text).cer


def thai_digit_report(truth: str, pred: str) -> dict[str, float | int | None]:
    """รายงานเฉพาะเลขไทย — ตัวชี้วัดหลักของงานนี้

    strict  ๒๕๖๙ ต้องออกมาเป็น ๒๕๖๙
    lenient แปลงเป็น 2569 ทั้งสองฝั่งก่อนเทียบ (ค่าถูกแต่รูปแบบอาจไม่ใช่เลขไทย)

    ช่องว่างระหว่างสองค่านี้บอกได้ทันทีว่า engine อ่าน "ค่า" ได้แต่พ่นเป็นเลขอารบิก
    """
    strict = compare(truth, pred)
    lenient = compare(truth, pred, lenient_digits=True)

    total = strict.total_by_class["thai_digit"]
    if not total:
        return {"total": 0, "strict": None, "lenient": None}

    lenient_total = lenient.total_by_class["arabic_digit"] or 1
    return {
        "total": total,
        "strict": strict.correct_by_class["thai_digit"] / total,
        "lenient": lenient.correct_by_class["arabic_digit"] / lenient_total,
    }


def aggregate(scores: list[LineScore]) -> dict[str, float | int | None]:
    """รวมคะแนนหลายบรรทัดเป็นตัวเลขเดียว

    CER รวมคิดจากผลรวมของรอยแก้หารด้วยผลรวมความยาวเฉลย ไม่ใช่ค่าเฉลี่ยของ CER
    รายบรรทัด เพราะบรรทัดสั้น ๆ ที่ผิดตัวเดียวจะทำให้ค่าเฉลี่ยเพี้ยนไปมาก
    """
    total_edits = sum(s.edits for s in scores)
    total_len = sum(s.truth_len for s in scores)

    correct: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    for s in scores:
        correct.update(s.correct_by_class)
        totals.update(s.total_by_class)

    out: dict[str, float | int | None] = {
        "cer": (total_edits / total_len) if total_len else None,
        "truth_chars": total_len,
        "edits": total_edits,
        "lines": len(scores),
    }
    for cls in CHAR_CLASSES:
        out[f"acc_{cls}"] = (correct[cls] / totals[cls]) if totals[cls] else None
        out[f"n_{cls}"] = totals[cls]
    return out


def top_confusions(scores: list[LineScore], limit: int = 20) -> list[tuple[str, str, int]]:
    """คู่ตัวอักษรที่สับสนบ่อยที่สุด — ใช้หาว่าอะไรแก้ได้ด้วย post-processing"""
    counter: Counter[tuple[str, str]] = Counter()
    for s in scores:
        counter.update(s.confusions)
    return [(a, b, n) for (a, b), n in counter.most_common(limit)]
