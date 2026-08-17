"""รันทุก engine บนหน้าที่มีเฉลย แล้วรายงานคะแนนเทียบกัน

รัน:  .venv\\Scripts\\python.exe compare_engines.py --pages 5

ความเป็นธรรมที่ต้องระวัง: เฉลยกรองลายน้ำออกไปแล้ว แต่ OCR อ่านลายน้ำเจอจริง
ถ้าไม่กรองฝั่ง OCR ด้วย ตัวที่อ่านเก่งจะถูกลงโทษเพราะอ่านเจอมากกว่า
จึงใช้ตัวกรองชุดเดียวกันกับทั้งสองฝั่ง
"""

from __future__ import annotations

import argparse

from thai_ocr_bench.config import IMAGE_DIR
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.metrics import (
    aggregate,
    align_lines,
    thai_digit_report,
    top_confusions,
)
from thai_ocr_bench.render import load_pages
from thai_ocr_bench.thai_text import CLASS_LABELS_TH, normalize
from thai_ocr_bench.truth import find_repeating_lines, load as load_truth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=5, help="จำนวนหน้าที่จะทดสอบ")
    args = parser.parse_args()

    truth = load_truth()
    pages = [p for p in load_pages() if p.page_id in truth][: args.pages]
    if not pages:
        print("ไม่มีหน้าที่มีเฉลย รัน build_truth.py ก่อน")
        return

    engines = [e for e in get_engines() if e.available()[0]]
    print(f"ทดสอบ {len(pages)} หน้า × {len(engines)} engine\n")

    raw: dict[str, dict[str, list[str]]] = {}
    timings: dict[str, list[float]] = {e.name: [] for e in engines}

    for page in pages:
        image = IMAGE_DIR / f"{page.page_id}.png"
        for engine in engines:
            result = engine.run(image, page.page_id)
            if not result.ok:
                print(f"  {engine.name} พังที่ {page.page_id}: {result.error}")
                continue
            raw.setdefault(engine.name, {})[page.page_id] = [
                ln.text for ln in result.lines
            ]
            timings[engine.name].append(result.core_ms or 0.0)
        print(f"  อ่านแล้ว {page.page_id}")

    # กรองลายน้ำจากฝั่ง OCR ด้วยตัวกรองเดียวกับที่ใช้กับเฉลย
    print()
    for name, per_page in raw.items():
        dropped = find_repeating_lines(per_page)
        if dropped:
            print(f"  กรองลายน้ำออกจากผลของ {name}: {len(dropped)} รูปแบบ")
        for page_id, lines in per_page.items():
            per_page[page_id] = [ln for ln in lines if ln.strip() not in dropped]

    scores: dict[str, list] = {}
    digits: dict[str, tuple[int, int]] = {}
    layout: dict[str, tuple[int, int, int, int]] = {}

    for engine in engines:
        per_page = raw.get(engine.name, {})
        collected = []
        d_total = d_correct = d_lenient = 0
        spurious = missed = truth_total = spurious_chars = 0

        for page in pages:
            truth_lines = truth[page.page_id].lines
            pred_lines = per_page.get(page.page_id, [])

            page_score = align_lines(truth_lines, pred_lines)
            collected.extend(page_score.matched)
            spurious += page_score.spurious_lines
            spurious_chars += page_score.spurious_chars
            missed += page_score.missed_lines
            truth_total += page_score.truth_lines

            # เลขไทยวัดจากคู่ที่จับได้ เพื่อไม่ให้ลายน้ำมากวน
            for pair in page_score.pairs:
                if pair.score is None or pair.pred_index is None:
                    continue
                report = thai_digit_report(pair.truth, pair.pred)
                if report["total"]:
                    n = int(report["total"])
                    d_total += n
                    d_correct += round(float(report["strict"] or 0) * n)
                    d_lenient += round(float(report["lenient"] or 0) * n)

        scores[engine.name] = collected
        digits[engine.name] = (d_correct, d_lenient, d_total)
        layout[engine.name] = (truth_total - missed, truth_total, spurious, spurious_chars)

    print("\n" + "=" * 92)
    print("ผลรวม  (จับคู่ทีละบรรทัด ลายน้ำและขยะไปอยู่ในช่อง 'บรรทัดเกิน')")
    print("=" * 92)
    header = (
        f"{'engine':<16}{'CER':>8}{'อ่านครบ':>12}{'บรรทัดเกิน':>13}"
        f"{'เลขไทย strict':>16}{'lenient':>10}{'วิ/หน้า':>9}"
    )
    print(header)
    print("-" * 92)
    for engine in engines:
        agg = aggregate(scores[engine.name])
        strict, lenient, total = digits[engine.name]
        found, truth_total, spurious, _ = layout[engine.name]
        pace = sum(timings[engine.name]) / max(1, len(timings[engine.name])) / 1000
        strict_txt = f"{strict}/{total} ({strict / total:.0%})" if total else "-"
        lenient_txt = f"{lenient / total:.0%}" if total else "-"
        print(
            f"{engine.name:<16}{agg['cer']:>7.1%}{f'{found}/{truth_total}':>12}"
            f"{spurious:>13}{strict_txt:>16}{lenient_txt:>10}{pace:>9.1f}"
        )

    print("\n" + "=" * 78)
    print("ความแม่นแยกตามชนิดอักขระ")
    print("=" * 78)
    names = [e.name for e in engines]
    print(f"{'ชนิด':<20}{'จำนวน':>9}" + "".join(f"{n:>16}" for n in names))
    print("-" * 78)
    ref = aggregate(scores[names[0]])
    for cls, label in CLASS_LABELS_TH.items():
        n = ref.get(f"n_{cls}") or 0
        if not n:
            continue
        row = f"{label:<20}{n:>9,}"
        for name in names:
            acc = aggregate(scores[name]).get(f"acc_{cls}")
            row += f"{acc:>15.1%}" if acc is not None else f"{'-':>16}"
        print(row)

    print("\n" + "=" * 78)
    print("คู่ที่สับสนบ่อยที่สุด (เฉลย -> ที่อ่านได้)")
    print("=" * 78)
    for name in names:
        pairs = top_confusions(scores[name], limit=8)
        shown = "  ".join(f"{a}->{b} ({n})" for a, b, n in pairs) or "ไม่มี"
        print(f"  {name:<16}{shown}")


if __name__ == "__main__":
    main()
