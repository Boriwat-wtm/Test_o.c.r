"""รัน OCR ทุกตัวบนทุกหน้า แล้วเก็บผลลงดิสก์

รันทีละ engine ให้จบก่อนขึ้นตัวถัดไป แล้วคืนหน่วยความจำ GPU ระหว่างกัน
เพราะการ์ดมี VRAM 6 GB โหลดหลายโมเดลพร้อมกันไม่ได้

รัน:
  .venv\\Scripts\\python.exe run_bench.py                    ทุก engine ทุกหน้า
  .venv\\Scripts\\python.exe run_bench.py -e paddle-th       เจาะ engine เดียว
  .venv\\Scripts\\python.exe run_bench.py --pages 8          จำกัดจำนวนหน้า
  .venv\\Scripts\\python.exe run_bench.py --redo             อ่านใหม่แม้มีผลเก่าอยู่
"""

from __future__ import annotations

import argparse
import gc
import time

from thai_ocr_bench import store
from thai_ocr_bench.config import IMAGE_DIR
from thai_ocr_bench.engines import get_engines
from thai_ocr_bench.render import load_pages
from thai_ocr_bench.versions import format_snapshot, snapshot


def free_gpu() -> None:
    """คืน VRAM ก่อนขึ้น engine ตัวถัดไป"""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="รัน OCR ทุกตัวแล้วเก็บผล")
    parser.add_argument("-e", "--engine", action="append", help="เจาะเฉพาะ engine นี้")
    parser.add_argument("--pages", type=int, help="จำกัดจำนวนหน้า")
    parser.add_argument("--redo", action="store_true", help="อ่านใหม่แม้มีผลเก่า")
    args = parser.parse_args()

    pages = load_pages()
    if not pages:
        print("ยังไม่มีภาพ รัน render_pages.py ก่อน")
        return
    if args.pages:
        pages = pages[: args.pages]

    engines = get_engines(args.engine)
    ready = []
    for engine in engines:
        ok, why = engine.available()
        if ok:
            ready.append(engine)
        else:
            print(f"ข้าม {engine.name}: {why}")
    if not ready:
        print("ไม่มี engine ที่พร้อมใช้")
        return

    print(f"\nสภาพแวดล้อม\n{format_snapshot()}\n")
    print(f"รัน {len(ready)} engine × {len(pages)} หน้า\n")

    results = store.load()

    for engine in ready:
        pending = [
            p
            for p in pages
            if args.redo or p.page_id not in results.get(engine.name, {})
        ]
        if not pending:
            print(f"[{engine.name}] มีผลครบแล้ว ข้าม")
            continue

        print(f"[{engine.name}] {len(pending)} หน้า")
        started = time.perf_counter()
        failures = 0

        for i, page in enumerate(pending, start=1):
            result = engine.run(IMAGE_DIR / f"{page.page_id}.png", page.page_id)
            results.setdefault(engine.name, {})[page.page_id] = store.from_result(result)
            store.save(results, {"versions": snapshot()})

            if not result.ok:
                failures += 1
                print(f"  {i}/{len(pending)} {page.page_id} พัง: {result.error}")
            else:
                pace = (result.core_ms or 0) / 1000
                print(
                    f"  {i}/{len(pending)} {page.page_id}  "
                    f"{len(result.lines):>3} บรรทัด  {pace:>6.1f}s"
                )

        total = time.perf_counter() - started
        note = f" ({failures} หน้าพัง)" if failures else ""
        print(f"  รวม {total / 60:.1f} นาที{note}\n")

        # ปล่อยโมเดลออกจาก VRAM ก่อนขึ้นตัวถัดไป
        for attr in ("_model", "_processor", "_reader", "_rec", "_det", "_detector", "_ocr"):
            if hasattr(engine, attr):
                setattr(engine, attr, None)
        free_gpu()

    print(f"เก็บผลไว้ที่ results/{store.RESULTS_FILE}")
    print("ดูผลรายหน้า:  .venv\\Scripts\\streamlit.exe run app.py")


if __name__ == "__main__":
    main()
