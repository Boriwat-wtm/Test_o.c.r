"""แผงสั่งสแกนกับแถบความคืบหน้า — ส่วนที่ "สั่งงาน" ไม่ใช่ส่วนที่ "ดูผล"

รัน run_bench.py เป็นคนละโปรเซส ไม่ใช่เรียกในหน้าเว็บ เพราะการอ่านหนึ่งหน้า
กิน 10-50 วินาที ถ้ารันในเธรดของ Streamlit หน้าเว็บจะค้างทั้งหน้าจนหมดเวลา
"""

from __future__ import annotations

import subprocess
import sys

import streamlit as st

from collections import Counter

from .. import history, progress, store
from ..config import CLEAN_IMAGE_DIR, IMAGE_DIR, RESULTS_DIR, ROOT, SOURCE_DIR
from ..engines.base import get_engines
from ..preprocess import clean_file
from ..render import PageInfo, load_pages, render_all
from .common import short_doc

def run_is_active(status) -> bool:
    """มีตัวรันทำงานอยู่จริงไหม — เพื่อไม่ให้กดสแกนซ้อนกันสองรอบ

    ถือว่าจบแล้วถ้าไฟล์สถานะบอกว่า finished หรือค้างจนเกิน STALE_SECONDS
    (ตัวรันตายกลางคันจะไม่ได้เขียน finished ให้ ปุ่มจะได้ไม่ล็อกค้าง)
    """
    return bool(status and not status.finished and not status.stale)


def start_scan(engines: list[str], docs: list[str], *, clean: bool, redo: bool) -> None:
    """สั่ง run_bench.py เป็นคนละโปรเซส แล้วปล่อยให้ progress_banner ตามสถานะเอง

    ไม่รัน OCR ในโปรเซสของหน้าเว็บ เพราะ engine หนักตัวจะบล็อกหน้าจนหมุนค้าง
    และ Streamlit รันสคริปต์ใหม่ทุกครั้งที่ผู้ใช้กดอะไร งานจะโดนตัดกลางคัน
    ทั้งสองฝั่งคุยกันผ่าน results/run_status.json อยู่แล้ว จึงใช้ช่องทางเดิม
    """
    # อ่านสถานะสด ๆ อีกครั้งตรงนี้ ค่าที่ปุ่มใช้ตัดสินใจมาจากตอนโหลดหน้า
    # ซึ่งอาจเก่าไปหลายวินาทีแล้ว สองโปรเซสเขียน results/ ทับกันจะได้ผลปนกัน
    if run_is_active(progress.load()):
        st.warning("มีตัวรันทำงานอยู่แล้ว ไม่สั่งซ้ำ")
        return

    cmd = [sys.executable, str(ROOT / "run_bench.py")]
    for name in engines:
        cmd += ["-e", name]
    for name in docs:
        cmd += ["--doc", name]
    if clean:
        cmd.append("--clean")
    if redo:
        cmd.append("--redo")

    # ต่อท้าย ไม่ทับ — เดิมเปิดด้วย "w" ทำให้ log ของรอบก่อนหายทุกครั้งที่กดสแกน
    # ตอนไล่หาสาเหตุว่ารอบไหนพังเพราะอะไรจึงไม่เหลืออะไรให้ดู
    log = RESULTS_DIR / "run_bench.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a", encoding="utf-8")
    handle.write(
        f"\n{'=' * 70}\n"
        f"เริ่มรอบใหม่ {history.now_iso()}\n"
        f"  เอกสาร {', '.join(docs)}\n"
        f"  engine {', '.join(engines)}"
        f"{' · ภาพลบลายน้ำ' if clean else ''}{' · อ่านใหม่' if redo else ''}\n"
        f"{'=' * 70}\n"
    )
    handle.flush()
    # DETACHED_PROCESS ไม่ให้ตัวรันตายตาม Streamlit ตอนกด Ctrl+C หรือรีโหลด
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=ROOT,
        creationflags=flags,
    )


@st.fragment(run_every="2s")
def scan_status() -> None:
    """สถานะการสแกนแบบย่อ วางไว้ใต้ปุ่มในแถบข้าง รีเฟรชตัวเองทุก 2 วินาที

    แถบใหญ่กลางหน้ามีข้อมูลครบกว่าอยู่แล้ว แต่ผู้ใช้กดปุ่มที่แถบซ้าย
    แล้วมองหาผลตรงนั้น ไม่ได้เงยไปดูกลางหน้า จึงต้องมีตัวย่อไว้ตรงจุดที่กด
    ต้องเป็น fragment ไม่งั้นค้างอยู่ที่สถานะตอนโหลดหน้าครั้งล่าสุด
    """
    status = progress.load()
    if status is None:
        return

    if status.finished:
        # done_engines นับตัวที่ถูกข้ามด้วย ถ้าดูแค่ตัวเลขนี้จะขึ้นว่า
        # "เสร็จแล้ว 100%" ทั้งที่ไม่ได้อ่านอะไรเลยสักหน้า ต้องดูประวัติรอบล่าสุด
        # ว่ามี engine ไหนได้ทำงานจริงบ้าง
        recent = history.load(limit=1)
        last = recent[0] if recent else {}
        engines = last.get("engines", [])
        ran = [e for e in engines if not e.get("skipped")]

        if engines and not ran:
            st.warning(
                f"ไม่ได้อ่านอะไรเลย — ทั้ง {len(engines)} engine มีผลของหน้าเหล่านี้"
                " อยู่แล้ว ถ้าต้องการอ่านซ้ำให้ติ๊ก **อ่านใหม่** ก่อนกด"
            )
            return

        note = f" · {status.failures} หน้าพัง" if status.failures else ""
        skipped = len(engines) - len(ran)
        skip_note = f" · ข้าม {skipped} ตัวที่มีผลแล้ว" if skipped else ""
        st.success(
            f"เสร็จแล้ว 100% — {len(ran) or len(status.done_engines)} engine × "
            f"{status.pages_total} หน้า{note}{skip_note}"
        )
        # ผลใหม่จะยังไม่โผล่จนกว่าหน้าจะโหลดใหม่ เพราะ store.load() ถูกเรียก
        # ตอนต้น main() ไปแล้ว ให้ปุ่มไว้แทนการ rerun เองเพื่อไม่ให้จอกระตุก
        if st.button("โหลดผลใหม่", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        return

    if status.stale:
        st.warning(f"ตัวรันหยุดไปแล้ว — ทำได้ {len(status.done_engines)} engine")
        return

    pct = status.overall_fraction
    st.progress(pct, text=f"{pct:.0%} · {status.current_engine or 'กำลังเริ่ม'}")
    st.caption(
        f"engine {len(status.done_engines) + 1}/{len(status.engines)} · "
        f"หน้า {status.pages_done}/{status.pages_total} · "
        f"เหลือ ~{fmt_eta(status.eta_seconds())}"
    )



def pending_reads(
    results: dict, pages: list[PageInfo], docs: list[str], engines: list[str],
    *, clean: bool, redo: bool,
) -> tuple[int, int]:
    """(จำนวนที่จะอ่านจริง, จำนวนที่ข้ามเพราะมีผลแล้ว)

    ใช้กติกาเดียวกับ run_bench.py คือข้ามหน้าที่มีผลอยู่แล้วเว้นแต่สั่ง --redo
    ต้องคำนวณฝั่งหน้าเว็บด้วย ไม่งั้นผู้ใช้กดแล้วจบใน 0 วินาทีโดยไม่รู้ว่าทำไม
    """
    ids = [p.page_id for p in pages if p.doc_name in set(docs)]
    total = len(ids) * len(engines)
    if redo:
        return total, 0
    suffix = "+clean" if clean else ""
    done = sum(
        1
        for name in engines
        for pid in ids
        if pid in results.get(name + suffix, {})
    )
    return total - done, done


def scan_panel(pages: list[PageInfo], results: dict) -> None:
    """แผงสั่งสแกนในแถบข้าง

    ตั้งใจให้ค่าเริ่มต้นคือ "ทุกอย่าง" โดยไม่ต้องเลือก เพราะถ้า default
    เป็นรายการเต็ม multiselect จะกาง chip ทุกตัวออกมาเรียงลง กินครึ่งแถบ
    ทั้งที่ส่วนใหญ่กดรันทั้งชุดอยู่แล้ว ว่าง = ทั้งหมด
    """
    status = progress.load()
    active = run_is_active(status)

    try:
        ready, blocked = [], {}
        for engine in get_engines(None):
            ok, why = engine.available()
            if ok:
                ready.append(engine.name)
            else:
                blocked[engine.name] = why
    except Exception as exc:  # engine ที่ import ไม่ผ่านไม่ควรทำหน้าเว็บล่ม
        st.error(f"อ่านรายชื่อ engine ไม่ได้: {exc}")
        return

    names = sorted(ready)
    docs = sorted({p.doc_name for p in pages})
    count = Counter(p.doc_name for p in pages)

    # ไฟล์ที่เพิ่งวางในโฟลเดอร์ต้นทางยังไม่มีภาพ และหน้าเว็บ cache รายการหน้าไว้
    # จึงไม่โผล่จนกว่าจะ render แล้วล้าง cache ซึ่งเดิมต้องออกไปพิมพ์เองใน terminal
    new_pdfs = sorted(
        p.stem for p in SOURCE_DIR.glob("*.pdf")
        if p.stem not in {pg.doc_name for pg in pages}
    ) if SOURCE_DIR.exists() else []
    if new_pdfs:
        st.warning(
            f"มี {len(new_pdfs)} ไฟล์ในโฟลเดอร์ต้นทางที่ยังไม่ได้แปลงเป็นภาพ:\n\n- "
            + "\n- ".join(short_doc(n, 30) for n in new_pdfs)
        )
    if st.button(
        "อ่านไฟล์ใหม่จากโฟลเดอร์ต้นทาง",
        use_container_width=True,
        type="primary" if new_pdfs else "secondary",
    ):
        with st.spinner("กำลังแปลง PDF เป็นภาพ…"):
            render_all()
            for page in load_pages():
                src = IMAGE_DIR / f"{page.page_id}.png"
                if src.exists():
                    clean_file(src, CLEAN_IMAGE_DIR / f"{page.page_id}.png")
        st.cache_data.clear()  # ไม่งั้นรายการหน้ายังเป็นชุดเดิมที่จำไว้
        st.rerun()

    st.subheader("สั่งสแกน", divider="gray")
    pick_docs = st.multiselect(
        "เอกสาร",
        docs,
        placeholder=f"ทุกเอกสาร ({len(docs)})",
        format_func=lambda d: f"{short_doc(d)} · {count[d]}",
    )
    pick_engines = st.multiselect(
        "engine", names, placeholder=f"ทุก engine ที่พร้อม ({len(names)})"
    )

    a, b = st.columns(2)
    clean = a.checkbox("ภาพลบลายน้ำ", value=False)
    redo = b.checkbox("อ่านใหม่", value=False)

    use_docs = pick_docs or docs
    use_engines = pick_engines or names
    todo, skip = pending_reads(
        results, pages, use_docs, use_engines, clean=clean, redo=redo
    )

    # ปุ่มต้องโผล่เสมอแม้กดไม่ได้ ถ้า return ทิ้งตอนไม่มี engine
    # ผู้ใช้จะหาปุ่มไม่เจอแล้วนึกว่าฟีเจอร์ไม่มีอยู่จริง
    if active:
        st.button("กำลังสแกนอยู่…", disabled=True, use_container_width=True)
    elif not names:
        st.button("เริ่มสแกน", disabled=True, use_container_width=True)
        st.caption("ยังไม่มี engine พร้อมใช้ — `uv sync --extra all`")
    elif todo == 0:
        # กดไปก็ข้ามหมดแล้วจบใน 0 วินาที ต้องบอกก่อนไม่ใช่ปล่อยให้กดแล้วงง
        st.button("เริ่มสแกน", disabled=True, use_container_width=True)
        st.caption(f"มีผลครบแล้วทั้ง {skip:,} ครั้ง — ติ๊ก **อ่านใหม่** ถ้าต้องการอ่านซ้ำ")
    else:
        note = f" · ข้าม {skip:,} ที่มีผลแล้ว" if skip else ""
        st.caption(f"จะอ่าน {todo:,} ครั้ง{note}")
        if st.button("เริ่มสแกน", type="primary", use_container_width=True):
            start_scan(use_engines, use_docs, clean=clean, redo=redo)
            st.rerun()

    scan_status()

    # ข้อมูลอ้างอิง ไม่ใช่ตัวควบคุม จึงอยู่ล่างสุดและพับไว้
    if blocked:
        with st.expander(f"อีก {len(blocked)} engine ยังใช้ไม่ได้"):
            for name, why in sorted(blocked.items()):
                st.caption(f"**{name}** — {why}")



def fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 90:
        return f"{seconds:.0f} วินาที"
    return f"{seconds / 60:.0f} นาที"


@st.fragment(run_every="3s")
def progress_banner(total_pages: int) -> None:
    """แถบความคืบหน้าของตัวรัน รีเฟรชตัวเองทุก 3 วินาที

    ใช้ st.fragment เพื่อให้รีเฟรชแค่ส่วนนี้ ไม่ต้องโหลดหน้าทั้งหน้าใหม่
    ซึ่งจะทำให้ตัวเลือกหน้าและ engine ที่ผู้ใช้เลือกไว้หลุด
    """
    status = progress.load()

    # ไม่มีไฟล์สถานะ (เช่นรันด้วยโค้ดรุ่นก่อน) — เดาจากจำนวนผลที่เก็บได้
    if status is None:
        results = store.load()
        if not results:
            return
        counts = {name: len(pages) for name, pages in results.items()}
        run_size = max(counts.values()) if counts else 0
        st.caption(
            "ไม่พบไฟล์สถานะการรัน — ประมาณจากผลที่เก็บได้: "
            + " · ".join(f"{n} {c}/{run_size}" for n, c in sorted(counts.items()))
        )
        return

    if status.finished:
        note = f" ({status.failures} หน้าพัง)" if status.failures else ""
        st.success(
            f"รันเสร็จแล้ว — {len(status.done_engines)} engine × "
            f"{status.pages_total} หน้า{note}"
        )
        return

    if status.stale:
        age = status.age_seconds or 0
        st.warning(
            f"ตัวรันไม่อัปเดตมา {age / 60:.0f} นาที น่าจะหยุดไปแล้ว — "
            f"ทำได้ {len(status.done_engines)}/{len(status.engines)} engine"
        )
        return

    engine_name = status.current_engine or "กำลังเริ่ม"
    overall = status.overall_fraction

    with st.container(border=True):
        st.markdown(
            f"**กำลังรัน `{engine_name}`** &nbsp; "
            f"engine ที่ {len(status.done_engines) + 1} จาก {len(status.engines)} &nbsp;·&nbsp; "
            f"เหลืออีกประมาณ {fmt_eta(status.eta_seconds())}",
            unsafe_allow_html=True,
        )
        st.progress(
            overall,
            text=f"รวมทั้งหมด {overall:.0%}",
        )
        st.progress(
            status.engine_fraction,
            text=(
                f"{engine_name} — {status.pages_done}/{status.pages_total} หน้า"
                + (
                    f" · หน้าล่าสุดใช้ {status.last_seconds:.1f}s"
                    if status.last_seconds
                    else ""
                )
            ),
        )

        waiting = [
            e
            for e in status.engines
            if e not in status.done_engines and e != status.current_engine
        ]
        if waiting:
            st.caption("รอคิว: " + " · ".join(waiting))


