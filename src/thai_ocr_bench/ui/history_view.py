"""แท็บประวัติการรัน — หนึ่งแถวคือหนึ่งรอบที่กดสแกน"""

from __future__ import annotations

import streamlit as st

from .. import history
from ..config import RESULTS_DIR

def view_history() -> None:
    st.subheader("ประวัติการรัน")
    st.caption(
        "หนึ่งแถวคือหนึ่งรอบที่กดสแกน เรียงจากรอบล่าสุดลงไป "
        "เก็บที่ `results/run_history.jsonl` ต่อท้ายอย่างเดียว ไม่เขียนทับ"
    )

    rows = history.load()
    if not rows:
        st.info(
            "ยังไม่มีประวัติ — เริ่มบันทึกตั้งแต่รอบถัดไปที่กดสแกน "
            "รอบก่อนหน้านี้ไม่ได้ถูกเก็บไว้เพราะยังไม่มีระบบนี้"
        )
        return

    st.caption(f"ทั้งหมด {len(rows)} รอบ")
    for i, run in enumerate(rows):
        no = len(rows) - i  # รอบที่ 1 คือรอบแรกสุดตามลำดับเวลา
        stamp = run.get("started_at", "?").replace("T", " ").replace("+00:00", "")
        ok = run.get("completed", False)
        head = f"{'✅' if ok else '⚠️'} รอบที่ {no} · {stamp} · {history.summarize(run)}"

        with st.expander(head, expanded=(i == 0)):
            engines_all = run.get("engines", [])
            ran = [e for e in engines_all if not e.get("skipped")]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("อ่านจริง", f"{sum(e.get('pages', 0) for e in ran):,} ครั้ง")
            c2.metric("บรรทัดที่ได้", f"{sum(e.get('lines', 0) for e in ran):,}")
            c3.metric("เวลา", f"{run.get('duration_s', 0) / 60:.1f} นาที")
            c4.metric("หน้าพัง", sum(e.get("failures", 0) for e in ran))

            source = "ภาพลบลายน้ำ" if run.get("clean") else "ภาพดิบ"
            flags = [f"ใช้{source}"]
            if run.get("redo"):
                flags.append("อ่านใหม่ทับของเก่า")
            if len(engines_all) - len(ran):
                flags.append(f"ข้าม {len(engines_all) - len(ran)} engine ที่มีผลแล้ว")
            if not ok:
                flags.append("**รอบนี้ไม่จบ — หยุดกลางคัน**")
            st.markdown(
                f"**เอกสาร** {' · '.join(run.get('docs', [])) or '-'} "
                f"({run.get('pages', 0)} หน้า)  \n"
                f"**สั่งด้วย** {' · '.join(flags)}"
            )

            table = []
            for e in run.get("engines", []):
                if e.get("skipped"):
                    # ต้องเป็น None ไม่ใช่ "-" — คอลัมน์เดียวกันมีทั้ง int กับ str
                    # ทำให้ pyarrow แปลงตารางไม่ผ่าน แล้วแท็บนี้พังทั้งแท็บ
                    # (ArrowTypeError: Expected bytes, got a 'int' object)
                    table.append(
                        {"engine": e["name"], "หน้า": None, "บรรทัด": None,
                         "พัง": None, "วินาที": None, "สถานะ": "ข้าม (มีผลครบแล้ว)"}
                    )
                else:
                    table.append(
                        {
                            "engine": e["name"],
                            "หน้า": e.get("pages", 0),
                            "บรรทัด": e.get("lines", 0),
                            "พัง": e.get("failures", 0),
                            "วินาที": round(float(e.get("seconds", 0)), 1),
                            "สถานะ": "เสร็จ",
                        }
                    )
            if table:
                st.dataframe(table, width="stretch", hide_index=True)
            else:
                st.caption("ไม่มี engine ไหนได้รันในรอบนี้")

    log = RESULTS_DIR / "run_bench.log"
    if log.exists():
        with st.expander("log ดิบของตัวรัน (ท้ายไฟล์)"):
            text = log.read_text(encoding="utf-8", errors="replace")
            st.code(text[-8000:] or "(ว่าง)")


