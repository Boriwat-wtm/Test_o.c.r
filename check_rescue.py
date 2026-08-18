"""ตรวจว่าการอ่านซ้ำแบบครอปช่วยจริงไหม โดยเทียบกับเฉลย

รัน:  .venv\\Scripts\\python.exe check_rescue.py

rescue.py แค่บันทึกว่าอ่านใหม่ได้อะไร ไม่ตัดสินว่าดีขึ้นหรือแย่ลง
ไฟล์นี้ทำหน้าที่ตัดสิน แยกกันเพื่อให้เปลี่ยนเกณฑ์วัดได้โดยไม่ต้องยิง API ใหม่

ต้องแยกให้ออกสามอย่าง ไม่ใช่นับแค่ "เปลี่ยนไปกี่จุด"
  ดีขึ้น   อ่านใหม่ใกล้เฉลยกว่าเดิม
  แย่ลง    อ่านใหม่ห่างเฉลยกว่าเดิม  <- ตัวนี้สำคัญที่สุด ถ้ามีมากแปลว่าวิธีนี้ใช้ไม่ได้
  เท่าเดิม เปลี่ยนแล้วแต่ผิดเท่ากัน หรือไม่เปลี่ยนเลย
"""

from __future__ import annotations

import json

from rapidfuzz.distance import Levenshtein

from thai_ocr_bench.config import RESULTS_DIR
from thai_ocr_bench.metrics import align_lines
from thai_ocr_bench.thai_text import normalize
from thai_ocr_bench.truth import load as load_truth


def main() -> None:
    path = RESULTS_DIR / "rescue.json"
    if not path.exists():
        raise SystemExit("ยังไม่มี results/rescue.json — รัน rescue.py ก่อน")

    report = json.loads(path.read_text(encoding="utf-8"))
    truth = load_truth()
    items = report["items"]

    better = worse = same = unknown = 0
    for item in items:
        page = truth.get(item["page_id"])
        if page is None:
            unknown += 1
            continue

        # หาบรรทัดในเฉลยที่ตรงกับบรรทัดนี้ที่สุด แล้ววัดระยะห่างก่อนและหลัง
        before, after = normalize(item["before"]), normalize(item["after"])
        if not after:
            unknown += 1
            continue
        best = max(
            (normalize(ln) for ln in page.lines),
            key=lambda t: Levenshtein.normalized_similarity(before, t),
            default="",
        )
        if not best:
            unknown += 1
            continue

        d_before = Levenshtein.distance(before, best)
        d_after = Levenshtein.distance(after, best)
        if d_after < d_before:
            better += 1
            print(f"ดีขึ้น  {item['page_id']} บรรทัด {item['grid_line'] + 1}"
                  f"  ผิด {d_before} -> {d_after}")
            print(f"        เดิม: {item['before'][:70]}")
            print(f"        ใหม่: {item['after'][:70]}")
            print(f"        เฉลย: {best[:70]}")
        elif d_after > d_before:
            worse += 1
            print(f"แย่ลง   {item['page_id']} บรรทัด {item['grid_line'] + 1}"
                  f"  ผิด {d_before} -> {d_after}")
            print(f"        เดิม: {item['before'][:70]}")
            print(f"        ใหม่: {item['after'][:70]}")
        else:
            same += 1

    print(f"\nจาก {len(items)} จุด: ดีขึ้น {better} · แย่ลง {worse} · "
          f"เท่าเดิม {same} · ตัดสินไม่ได้ {unknown}")
    if worse > better:
        print("วิธีนี้ทำให้แย่ลงมากกว่าดีขึ้น — อย่าเอาผลไปทับของเดิม")
    elif better:
        print("ช่วยได้จริง แต่ยังต้องดูภาพยืนยันทีละจุดก่อนเอาไปใช้")


if __name__ == "__main__":
    main()
