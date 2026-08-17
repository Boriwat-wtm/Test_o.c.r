"""วัดความแม่นของ OCR โดยเทียบกับเฉลย

หลักการ: เทียบทีละตัวอักษรด้วย edit distance แล้วเอา "รอยแก้" ที่ได้ไปใช้ต่อ
ทั้งการคิด CER, ความแม่นรายกลุ่มอักขระ และการไฮไลต์จุดผิดบนหน้าเว็บ
ทุกอย่างจึงมาจากการเทียบครั้งเดียวกัน ตัวเลขกับสีที่เห็นตรงกันเสมอ
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

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

    page = PageScore(truth_lines=sum(1 for t in norm_truth if t))

    for ti, truth_line in enumerate(truth_lines):
        if not norm_truth[ti]:
            continue
        if ti in matches:
            pi = matches[ti]
            score = compare(truth_line, pred_lines[pi])
            page.matched.append(score)
            page.pairs.append(LinePair(ti, pi, truth_line, pred_lines[pi], score))
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
