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
from datetime import datetime, timezone

from thai_ocr_bench import history, progress, store
from thai_ocr_bench.config import CLEAN_IMAGE_DIR, IMAGE_DIR
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
    parser.add_argument(
        "--doc",
        action="append",
        help="เจาะเฉพาะเอกสารชื่อนี้ (ใส่ซ้ำได้) — --pages เอาแต่หน้าแรก ๆ "
        "ซึ่งเป็นของเอกสารเดียวจนไม่ได้แตะไฟล์ที่เพิ่งเพิ่ม",
    )
    parser.add_argument("--redo", action="store_true", help="อ่านใหม่แม้มีผลเก่า")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="ใช้ภาพที่ลบลายน้ำแล้ว เก็บผลแยกชื่อเป็น <engine>+clean เพื่อเทียบกับชุดดิบ",
    )
    args = parser.parse_args()

    image_dir = CLEAN_IMAGE_DIR if args.clean else IMAGE_DIR
    suffix = "+clean" if args.clean else ""
    if args.clean and not any(CLEAN_IMAGE_DIR.glob("*.png")):
        print("ยังไม่มีภาพที่ลบลายน้ำ รัน clean_images.py ก่อน")
        return

    pages = load_pages()
    if not pages:
        print("ยังไม่มีภาพ รัน render_pages.py ก่อน")
        return
    if args.doc:
        wanted = set(args.doc)
        unknown = wanted - {p.doc_name for p in pages}
        if unknown:
            print("ไม่รู้จักเอกสาร: " + ", ".join(sorted(unknown)))
            return
        pages = [p for p in pages if p.doc_name in wanted]
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

    # เขียนสถานะให้หน้าเว็บอ่าน เพื่อโชว์แถบความคืบหน้าระหว่างรัน
    status = progress.RunStatus(
        engines=[e.name + suffix for e in ready],
        pages_total=len(pages),
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    progress.save(status)

    # บันทึกรอบนี้ลงประวัติ — status.json เก็บแค่รอบปัจจุบันแล้วถูกทับ
    # จึงตอบไม่ได้ว่ารอบก่อน ๆ รันอะไรไปบ้าง
    run_started = time.perf_counter()
    record: dict = {
        "started_at": status.started_at,
        "docs": sorted({p.doc_name for p in pages}),
        "pages": len(pages),
        "clean": bool(args.clean),
        "redo": bool(args.redo),
        "engines": [],
    }

    try:
        _run_engines(ready, pages, results, status, record, args, image_dir, suffix)
    finally:
        # ต้องเขียนแม้พังกลางคัน ไม่งั้นรอบที่ล้มจะหายไปจากประวัติเงียบ ๆ
        # ซึ่งเป็นรอบที่อยากรู้ที่สุดว่าเกิดอะไรขึ้น
        record["finished_at"] = history.now_iso()
        record["duration_s"] = time.perf_counter() - run_started
        record["completed"] = status.finished
        history.append(record)

    print(f"เก็บผลไว้ที่ results/{store.RESULTS_FILE}")
    print("ดูผลรายหน้า:  .venv\\Scripts\\streamlit.exe run app.py")


def _run_engines(ready, pages, results, status, record, args, image_dir, suffix) -> None:
    """วนรันทีละ engine — แยกออกมาเพื่อให้ main() ห่อด้วย try/finally ได้"""
    for engine in ready:
        key = engine.name + suffix
        pending = [
            p for p in pages if args.redo or p.page_id not in results.get(key, {})
        ]
        if not pending:
            print(f"[{key}] มีผลครบแล้ว ข้าม")
            status.done_engines.append(key)
            progress.save(status)
            record["engines"].append({"name": key, "skipped": True})
            continue

        print(f"[{key}] {len(pending)} หน้า")
        started = time.perf_counter()
        failures = 0
        lines_read = 0

        status.current_engine = key
        status.pages_done = 0
        status.pages_total = len(pending)
        progress.save(status)

        for i, page in enumerate(pending, start=1):
            status.current_page = page.page_id
            progress.save(status)

            result = engine.run(image_dir / f"{page.page_id}.png", page.page_id)
            results.setdefault(key, {})[page.page_id] = store.from_result(result)
            store.save(results, {"versions": snapshot()})

            if not result.ok:
                failures += 1
                print(f"  {i}/{len(pending)} {page.page_id} พัง: {result.error}")
            else:
                lines_read += len(result.lines)
                pace = (result.core_ms or 0) / 1000
                print(
                    f"  {i}/{len(pending)} {page.page_id}  "
                    f"{len(result.lines):>3} บรรทัด  {pace:>6.1f}s"
                )

            status.pages_done = i
            status.failures = failures
            status.last_seconds = (result.core_ms or 0) / 1000
            progress.save(status)

        total = time.perf_counter() - started
        note = f" ({failures} หน้าพัง)" if failures else ""
        print(f"  รวม {total / 60:.1f} นาที{note}\n")

        record["engines"].append(
            {
                "name": key,
                "pages": len(pending),
                "lines": lines_read,
                "failures": failures,
                "seconds": total,
            }
        )

        status.done_engines.append(key)
        status.current_engine = None
        status.current_page = None
        progress.save(status)

        # ปล่อยโมเดลออกจาก VRAM ก่อนขึ้นตัวถัดไป
        for attr in ("_model", "_processor", "_reader", "_rec", "_det", "_detector", "_ocr"):
            if hasattr(engine, attr):
                setattr(engine, attr, None)
        free_gpu()

    status.finished = True
    status.current_engine = None
    status.current_page = None
    progress.save(status)


if __name__ == "__main__":
    main()
