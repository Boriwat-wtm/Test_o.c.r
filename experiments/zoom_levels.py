"""ขยายภาพก่อนเข้า OCR แล้วอ่านดีขึ้นไหม — วัด x1 x2 x4 บนหน้าเดียวกัน

คำถามนี้สำคัญเพราะ render.py มีตรรกะที่ลด zoom ลงเมื่อเจอสแกนความละเอียดต่ำ
โดยให้เหตุผลว่า "ขยายแล้วไม่ได้รายละเอียดเพิ่มขึ้นจริง แค่ทำไฟล์ใหญ่ขึ้น"
ซึ่งจริงแค่ครึ่งเดียว — ไม่มีข้อมูลใหม่ก็จริง แต่ engine ส่วนใหญ่มีความสูง
ตัวอักษรขั้นต่ำที่มันอ่านออก
  Tesseract  ทำงานดีที่สุดเมื่อ x-height ราว 30 px
  TrOCR      ถูกเทรนกับภาพบรรทัดสูง 32-64 px (ดู thai_trocr.MIN_LINE_HEIGHT)
สแกน 72 DPI จึงอาจมีตัวอักษรเล็กเกินกว่าที่ engine จะอ่านออก
การขยายด้วย interpolation ที่ดีก็ช่วยได้จริงแม้ไม่มีข้อมูลใหม่

ต้องแยกสองกรณีให้ชัด ไม่งั้นสรุปผิด
  หน้าสแกน   ขยายจาก PNG ที่มีอยู่ = interpolation ล้วน ไม่มีข้อมูลใหม่
  หน้า vector  render จาก PDF ใหม่ที่ DPI สูงขึ้น = ได้รายละเอียดเพิ่มจริง
สคริปต์นี้เลือกวิธีให้อัตโนมัติตามว่าหน้านั้นมีภาพฝังอยู่หรือเป็น vector
แล้วบอกในผลลัพธ์ด้วยว่าใช้วิธีไหน

รัน:
  uv run python experiments/zoom_levels.py                       หน้าเริ่มต้น
  uv run python experiments/zoom_levels.py docb7ac9c_p001        เจาะหน้า
  uv run python experiments/zoom_levels.py docb7ac9c_p001 -e tesseract-tha
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pymupdf
from PIL import Image

sys.path.insert(0, "src")

from thai_ocr_bench.config import IMAGE_DIR, SOURCE_DIR  # noqa: E402
from thai_ocr_bench.engines import get_engines  # noqa: E402
from thai_ocr_bench.metrics import align_lines, page_cer  # noqa: E402
from thai_ocr_bench.render import doc_id_for, load_pages  # noqa: E402
from thai_ocr_bench.thai_text import THAI_DIGITS, normalize  # noqa: E402
from thai_ocr_bench.truth import load as load_truth  # noqa: E402

SCALES = (1, 2, 4)
OUT_DIR = Path("data/zoom_test")
LOG_DIR = Path("results/zoom_diff")

# x4 ของหน้า A4 ที่ 300 DPI คือ 139 ล้านพิกเซล เกินเพดานกันภาพระเบิดของ Pillow
# ปลดได้เพราะภาพมาจากไฟล์ที่เราสร้างเองในเครื่อง ไม่ใช่ของที่รับมาจากภายนอก
Image.MAX_IMAGE_PIXELS = None


def source_pdf(doc_id: str) -> Path | None:
    for pdf in sorted(SOURCE_DIR.glob("*.pdf")):
        if doc_id_for(pdf) == doc_id:
            return pdf
    return None


def make_variants(page_id: str, base_dpi: int) -> list[tuple[int, Path, str, tuple]]:
    """สร้างภาพทุกตัวคูณ คืน (ตัวคูณ, path, วิธีที่ใช้, ขนาดพิกเซล)"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    info = {p.page_id: p for p in load_pages()}[page_id]
    pdf = source_pdf(info.doc_id)

    with pymupdf.open(pdf) as doc:
        page = doc[info.page_no - 1]
        # หน้าที่ไม่มีภาพฝังอยู่เลย = vector ล้วน render ใหม่ได้รายละเอียดจริง
        vector = not page.get_images(full=True)

        out = []
        for scale in SCALES:
            path = OUT_DIR / f"{page_id}_x{scale}.png"
            if vector:
                zoom = base_dpi * scale / 72.0
                matrix = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                pix.save(path)
                size = (pix.width, pix.height)
                how = f"render {base_dpi * scale} DPI"
            else:
                with Image.open(IMAGE_DIR / f"{page_id}.png") as im:
                    if scale == 1:
                        im.save(path)
                        size = im.size
                    else:
                        big = im.resize(
                            (im.width * scale, im.height * scale), Image.LANCZOS
                        )
                        big.save(path)
                        size = big.size
                how = "ขยายภาพ (LANCZOS)"
            out.append((scale, path, how, size))
    return out


def per_truth_line(truth_lines: list[str], pred_lines: list[str]) -> dict[int, tuple[str, float]]:
    """เฉลยบรรทัดที่ i -> (ข้อความที่ OCR อ่านได้, CER ของบรรทัดนั้น)

    ใช้ align_lines ตัวเดียวกับที่หน้าเว็บใช้คิดคะแนน จะได้ไม่มีสองมาตรฐาน
    บรรทัดที่ OCR ไม่ได้อ่านเลยคืน CER 1.0 เพื่อให้เทียบกับระดับอื่นได้
    """
    score = align_lines(truth_lines, pred_lines)
    out: dict[int, tuple[str, float]] = {}
    matched = iter(score.matched)
    for pair in score.pairs:
        if pair.truth_index is None:
            continue
        if pair.pred_index is None:
            out[pair.truth_index] = ("(ไม่ได้อ่านบรรทัดนี้)", 1.0)
        else:
            line = next(matched, None)
            out[pair.truth_index] = (pair.pred, line.cer if line else 0.0)
    return out


def write_diff_log(
    page_id: str, engine: str, truth_lines: list[str],
    by_scale: dict[int, list[str]], path: Path,
) -> int:
    """เขียน log ว่าแต่ละระดับการขยายอ่านต่างกันตรงบรรทัดไหน คืนจำนวนบรรทัดที่ต่าง

    ตอบคำถามที่ตัวเลข CER รวมตอบไม่ได้ — รู้ว่าดีขึ้น 1% แต่ไม่รู้ว่าดีขึ้นตรงไหน
    และดีขึ้นเพราะอ่านคำที่เคยผิดได้ถูก หรือเพราะบังเอิญผิดอีกแบบที่ใกล้เฉลยกว่า
    """
    scales = sorted(by_scale)
    base = scales[0]
    per_scale = {s: per_truth_line(truth_lines, by_scale[s]) for s in scales}

    rows = []
    for i, truth in enumerate(truth_lines):
        texts = {s: per_scale[s].get(i, ("(ไม่ได้อ่าน)", 1.0)) for s in scales}
        if len({normalize(t) for t, _ in texts.values()}) == 1:
            continue  # ทุกระดับอ่านได้เหมือนกัน ไม่ต้องรายงาน
        rows.append((i, truth, texts))

    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {page_id} · {engine}\n\n")
        fh.write(
            f"เทียบผลของแต่ละตัวคูณกับเฉลยทีละบรรทัด "
            f"แสดงเฉพาะบรรทัดที่อ่านได้ไม่เหมือนกัน "
            f"({len(rows)} จาก {len(truth_lines)} บรรทัด)\n\n"
        )
        for i, truth, texts in rows:
            best = min(texts.values(), key=lambda v: v[1])[1]
            fh.write(f"## บรรทัดที่ {i + 1}\n\n")
            fh.write(f"เฉลย  {truth}\n\n")
            for s in scales:
                text, cer = texts[s]
                mark = " <-- ดีที่สุด" if cer == best and cer < texts[base][1] else ""
                if s == base:
                    mark = " (ฐาน)"
                fh.write(f"  x{s}  CER {cer:6.1%}  {text}{mark}\n")
            fh.write("\n")
    return len(rows)


def stats(lines: list[str]) -> tuple[int, int, int, int]:
    text = "".join(lines)
    return (
        len(lines),
        len(text),
        sum(text.count(d) for d in THAI_DIGITS),
        sum(text.count(d) for d in "0123456789"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="วัดผลของการขยายภาพก่อนเข้า OCR")
    parser.add_argument("page", nargs="?", default="docb7ac9c_p001")
    parser.add_argument("-e", "--engine", action="append", help="เจาะเฉพาะ engine นี้")
    parser.add_argument("--dpi", type=int, default=300, help="DPI ฐานของ x1")
    args = parser.parse_args()

    pages = {p.page_id: p for p in load_pages()}
    if args.page not in pages:
        print(f"ไม่รู้จักหน้า {args.page}")
        return
    info = pages[args.page]

    engines = [e for e in get_engines(args.engine) if e.available()[0]]
    if not engines:
        print("ไม่มี engine ที่พร้อมใช้")
        return

    variants = make_variants(args.page, args.dpi)
    truth = load_truth().get(args.page)

    print(f"\nหน้า {args.page} — {info.doc_name} หน้า {info.page_no}")
    print(f"วิธีสร้างภาพ: {variants[0][2]}")
    if not truth:
        print("หน้านี้ไม่มีเฉลย จึงไม่มีคอลัมน์ CER — ดูเลขไทย/อารบิกแทน")
    print()
    for scale, _, _, size in variants:
        print(f"  x{scale}  {size[0]}x{size[1]} พิกเซล")
    print()

    header = f"{'engine':<16}{'ขยาย':>6}{'บรรทัด':>8}{'ตัวอักษร':>10}"
    header += f"{'เลขไทย':>8}{'อารบิก':>8}{'วินาที':>8}"
    if truth:
        header += f"{'CER หน้า':>10}"
    print(header)
    print("-" * len(header) * 2)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    for engine in engines:
        by_scale: dict[int, list[str]] = {}
        for scale, path, _, _ in variants:
            started = time.perf_counter()
            result = engine.run(path, f"{args.page}_x{scale}")
            elapsed = time.perf_counter() - started

            if not result.ok:
                print(f"{engine.name:<16}{'x' + str(scale):>6}  พัง: {result.error}")
                continue

            lines = [ln.text for ln in result.lines]
            by_scale[scale] = lines
            n_lines, chars, thai, arabic = stats(lines)
            row = f"{engine.name:<16}{'x' + str(scale):>6}{n_lines:>8}{chars:>10}"
            row += f"{thai:>8}{arabic:>8}{elapsed:>8.1f}"
            if truth:
                cer = page_cer(truth.lines, lines)
                row += f"{cer:>9.2%}" if cer is not None else f"{'-':>10}"
            print(row)

        # log รายบรรทัดต้องมีเฉลยถึงจะบอกได้ว่าที่ต่างกันนั้นดีขึ้นหรือแย่ลง
        if truth and len(by_scale) > 1:
            log = LOG_DIR / f"{args.page}_{engine.name}.md"
            n = write_diff_log(args.page, engine.name, truth.lines, by_scale, log)
            written.append((log, n))
        print()

    for log, n in written:
        print(f"log รายบรรทัด ({n} บรรทัดที่อ่านต่างกัน): {log}")
    if truth is None:
        print("หน้านี้ไม่มีเฉลย จึงไม่ได้เขียน log รายบรรทัด")
    print(f"ภาพที่ใช้ทดสอบเก็บไว้ที่ {OUT_DIR}/ ลบทิ้งได้")


if __name__ == "__main__":
    main()
