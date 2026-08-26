"""แท็บเปรียบเทียบ — split view ภาพจริงคู่กับผลของทุก engine

การแสดงผลทั้งหมดอยู่ใน viewer.py เพราะ Streamlit ทำสี่อย่างนี้ตรง ๆ ไม่ได้
(ซูม/ลากรูป, scroll แยกฝั่ง, hover ไฮไลต์กรอบ, สลับโหมดโดยไม่รีเซ็ต scroll)
ไฟล์นี้ทำหน้าที่คำนวณคะแนนแล้วส่งข้อมูลเข้าไปเป็น JSON เท่านั้น
"""

from __future__ import annotations

import html
from collections import Counter

import streamlit as st

from .. import history, markdown_out
from ..config import IMAGE_DIR
from ..metrics import align_lines, compare, page_cer, thai_digit_report
from ..render import PageInfo
from ..suspect import thai_digit_document
from ..thai_text import THAI_DIGITS, normalize
from ..truth import load as load_truth
from ..viewer import EngineRecord, LineRecord, build_html
from ..rescue_crop import ZOOM
from .common import (
    cached_image,
    page_label,
    rescue_crop_uri,
    unstable_points,
    engine_group,
    image_dir_for,
    merges_lines,
    repeated_line,
)
from .theme import cer_tone, rule_findings_inner, spans_to_inner

def _unscored_record(name: str, stored) -> EngineRecord:
    """ผลของ engine บนหน้าที่ยังไม่มีเฉลย — ข้อความล้วน ไม่มีคะแนน

    ห้ามเรียก align_lines ด้วยเฉลยว่าง เพราะทุกบรรทัดจะกลายเป็น "เกินมา"
    แล้วป้ายจะขึ้น "อ่านครบ 0/0" กับ "เกิน N บรรทัด" ซึ่งอ่านแล้วเข้าใจผิด
    ว่า engine พัง ทั้งที่เราแค่ยังไม่มีอะไรให้เทียบ
    """
    badges = [
        {"label": f"{len(stored.lines)} บรรทัด", "tone": "good"},
        {"label": f"{stored.core_ms / 1000:.1f}s", "tone": "good"},
    ]
    notes = [{"kind": "info", "text": "ยังไม่มีเฉลยหน้านี้ — แสดงข้อความที่อ่านได้ ไม่มีคะแนน"}]

    loop = repeated_line(stored.lines)
    if loop:
        text, count = loop
        notes.append(
            {
                "kind": "error",
                "text": f"engine นี้ติดลูป — พ่นบรรทัดเดิมซ้ำ {count} ครั้ง",
            }
        )

    thai_doc = thai_digit_document(stored.lines)
    lines = [
        LineRecord(
            kind="matched",
            html=rule_findings_inner(line, thai_doc=thai_doc),
            box=stored.boxes[i] if i < len(stored.boxes) else None,
            conf=stored.confidences[i] if i < len(stored.confidences) else None,
        )
        for i, line in enumerate(stored.lines)
    ]
    group, variant = engine_group(name)
    return EngineRecord(
        name=name,
        group=group,
        variant=variant,
        badges=badges,
        notes=notes,
        lines=lines,
        has_boxes=any(b for b in stored.boxes),
    )


def _engine_record(
    name: str, stored, truth_lines: list[str]
) -> EngineRecord | None:
    """แปลงผลดิบของ engine หนึ่งตัวเป็นข้อมูลที่ component ใช้ได้

    truth_lines ว่างได้ หน้าที่ยังไม่มีเฉลยจะแสดงข้อความที่อ่านได้เฉย ๆ
    โดยไม่มีคะแนน ดีกว่าซ่อนทั้งหน้าเพราะยังเอาไปเทียบกับภาพด้วยตาได้
    """
    if stored is None:
        group, variant = engine_group(name)
        return EngineRecord(
            name=name,
            group=group,
            variant=variant,
            notes=[{"kind": "info", "text": "ยังไม่ได้อ่านหน้านี้"}],
        )
    if not stored.ok:
        group, variant = engine_group(name)
        return EngineRecord(
            name=name,
            group=group,
            variant=variant,
            notes=[{"kind": "error", "text": f"พัง: {html.escape(str(stored.error))}"}],
        )

    if not truth_lines:
        return _unscored_record(name, stored)

    score = align_lines(truth_lines, stored.lines)
    digits = thai_digit_report("\n".join(truth_lines), "\n".join(stored.lines))
    whole = page_cer(truth_lines, stored.lines)

    badges: list[dict] = []
    if score.matched_cer is not None:
        badges.append(
            {"label": f"CER บรรทัด {score.matched_cer:.1%}", "tone": cer_tone(score.matched_cer)}
        )
    if whole is not None:
        badges.append({"label": f"CER หน้า {whole:.1%}", "tone": cer_tone(whole)})
    badges.append(
        {
            "label": f"อ่านครบ {score.truth_lines - score.missed_lines}/{score.truth_lines}",
            "tone": "good" if (score.recall or 0) >= 0.95 else "bad",
        }
    )
    if score.spurious_lines:
        badges.append({"label": f"เกิน {score.spurious_lines} บรรทัด", "tone": "warn"})
    if digits["total"]:
        strict = float(digits["strict"] or 0)
        badges.append(
            {"label": f"เลขไทย {strict:.0%}", "tone": "good" if strict >= 0.9 else "bad"}
        )
    badges.append({"label": f"{stored.core_ms / 1000:.1f}s", "tone": "good"})

    notes: list[dict] = []
    loop = repeated_line(stored.lines)
    if loop:
        text, count = loop
        notes.append(
            {
                "kind": "error",
                "text": f"engine นี้ติดลูป — พ่นบรรทัดเดิมซ้ำ {count} ครั้ง ผลของหน้านี้ใช้เทียบไม่ได้",
            }
        )
    elif (ratio := merges_lines(truth_lines, stored.lines)) is not None:
        notes.append(
            {
                "kind": "info",
                "text": f"engine นี้รวมหลายบรรทัดเป็นก้อนเดียว (ยาวกว่าเฉลย {ratio:.1f} เท่า) "
                "ค่าอ่านครบจึงต่ำผิดปกติทั้งที่อ่านถูก — ให้ดู CER หน้า เป็นหลัก",
            }
        )

    def box_of(i: int | None):
        if i is None or i >= len(stored.boxes):
            return None
        return stored.boxes[i]

    def conf_of(i: int | None):
        if i is None or i >= len(stored.confidences):
            return None
        return stored.confidences[i]

    records: list[LineRecord] = []
    for pair in score.pairs:
        if pair.truth_index is not None and pair.pred_index is None:
            records.append(
                LineRecord(
                    kind="missed",
                    html="ไม่ได้อ่านบรรทัดนี้ &nbsp;<span style='opacity:.6'>("
                    + html.escape(pair.truth[:70])
                    + ")</span>",
                )
            )
        elif pair.truth_index is not None:
            display = compare(pair.truth, pair.pred, keep_spaces=True)
            records.append(
                LineRecord(
                    kind="matched",
                    html=spans_to_inner(display.spans),
                    box=box_of(pair.pred_index),
                    conf=conf_of(pair.pred_index),
                )
            )
        else:
            records.append(
                LineRecord(
                    kind="spurious",
                    html="เกินมา: " + html.escape(pair.pred[:90]),
                    box=box_of(pair.pred_index),
                    conf=conf_of(pair.pred_index),
                )
            )

    group, variant = engine_group(name)
    return EngineRecord(
        name=name,
        group=group,
        variant=variant,
        badges=badges,
        notes=notes,
        lines=records,
        has_boxes=any(b for b in stored.boxes),
    )



# ── หน้า 3 เปรียบเทียบ ───────────────────────────────────────────────────
def view_compare(pages: list[PageInfo], results: dict) -> None:
    """แท็บเปรียบเทียบ — ใช้ HTML component ตัวเดียวจบ

    ฝั่ง Python ทำแค่คำนวณคะแนนแล้วเตรียมข้อมูล ส่วนการแสดงผลทั้งหมด
    (split view, ซูม/ลากรูป, scroll แยกฝั่ง, hover ไฮไลต์กรอบ, สลับโหมด)
    อยู่ใน viewer.py เพราะ Streamlit ทำสี่อย่างนั้นตรง ๆ ไม่ได้
    """
    truth = load_truth()

    # เลือกได้ทุกหน้า ไม่ใช่เฉพาะหน้าที่มีเฉลย เฉลยสร้างอัตโนมัติจาก text layer
    # ไฟล์สแกนจึงไม่มี แล้วเคยหายไปจากช่องเลือกเงียบ ๆ ทั้งที่ยังดูผลเทียบกับภาพได้
    # หน้าที่ไม่มีเฉลยจะแสดงข้อความที่อ่านได้โดยไม่มีคะแนน
    #
    # แยกเอกสารกับหน้าเป็นคนละช่อง เฉพาะแท็บนี้ เพราะเป็นแท็บที่ต้องสลับหน้าถี่สุด
    # รวมเป็นช่องเดียวแล้วทุกบรรทัดขึ้นต้นด้วยชื่อเอกสารซ้ำกัน ต่างแค่เลขหน้าท้ายสุด
    docs = sorted({p.doc_name for p in pages})
    per_doc = Counter(p.doc_name for p in pages)

    # แถวควบคุมมีสองหน้าที่ที่ไม่ควรปนกัน — "เลือกหน้าไหน" กับ "แสดงยังไง"
    # ของเดิมยัดทั้งหกช่องเรียงกันในแถวเดียว ทำให้ช่องเลือกเอกสารกับ engine
    # แคบจนอ่านชื่อไม่จบ ตอนนี้เหลือแต่การเลื่อนหน้าไว้ในแถว
    # ส่วนตัวเลือกการแสดงผลย้ายไปอยู่ในปุ่มกาง ซึ่งตั้งครั้งเดียวแล้วแทบไม่แตะอีก
    top = st.columns([3.4, 1.5, 0.4, 0.4, 1.5])
    doc = top[0].selectbox(
        "เอกสาร",
        docs,
        format_func=lambda d: f"{d}  ({per_doc[d]} หน้า)",
        label_visibility="collapsed",
        key="cmp_doc",
    )
    subset = [p for p in pages if p.doc_name == doc]
    page_labels = {
        f"หน้า {p.page_no}" + ("" if p.page_id in truth else "  ·  ยังไม่มีเฉลย"): p
        for p in subset
    }
    keys = list(page_labels)

    # ปุ่มเลื่อนหน้าต้องมาก่อน selectbox ในลำดับโค้ด แม้จะแสดงผลอยู่ถัดไปทางขวา
    # (คอลัมน์คุมตำแหน่งที่วาด ส่วนลำดับโค้ดคุมลำดับการทำงาน)
    #
    # เพราะทางเดียวที่จะเปลี่ยนค่าของ selectbox ที่มี key ได้ คือเขียน
    # st.session_state["cmp_page"] ก่อนที่ widget จะถูกสร้างในรอบนั้น
    # เขียนทีหลังจะโยน StreamlitAPIException ส่วนการส่ง index= ก็ไม่มีผล
    # เพราะเมื่อ widget มี key แล้ว Streamlit จะใช้ค่าที่จำไว้ทับ index เสมอ
    # (ลองมาแล้วทั้งสองแบบ แบบแรกพัง แบบหลังกดแล้วหน้าไม่ขยับ)
    if st.session_state.get("cmp_page") not in keys:
        st.session_state.pop("cmp_page", None)  # เปลี่ยนเอกสารแล้วรายการหน้าเปลี่ยนตาม
    here = keys.index(st.session_state.get("cmp_page", keys[0]))

    if top[2].button("‹", disabled=here == 0, width="stretch",
                     help="หน้าก่อนหน้า"):
        st.session_state["cmp_page"] = keys[here - 1]
        st.rerun()
    if top[3].button("›", disabled=here >= len(keys) - 1, width="stretch",
                     help="หน้าถัดไป"):
        st.session_state["cmp_page"] = keys[here + 1]
        st.rerun()

    picked_label = top[1].selectbox(
        "หน้า", keys, label_visibility="collapsed", key="cmp_page"
    )
    picked = page_labels[picked_label]
    # ว่าง = ทุกตัว เหมือนแผงสั่งสแกน ถ้า default เป็นรายการเต็ม
    # มันจะกาง chip ทั้ง 8 ตัวอัดอยู่ในคอลัมน์แคบ ๆ จนบังแถวควบคุมทั้งแถว
    all_engines = sorted(results)
    with top[4].popover("⚙️ การแสดงผล", width="stretch"):
        chosen = (
            st.multiselect(
                "engine ที่จะแสดง",
                all_engines,
                placeholder=f"ทุก engine ({len(all_engines)})",
                help="ว่างไว้ = แสดงทุกตัว",
            )
            or all_engines
        )
        tall = st.radio(
            "ความสูงของหน้าต่าง", ["ปกติ", "สูง", "เต็มจอ"], horizontal=True
        )
    height = {"ปกติ": 760, "สูง": 900, "เต็มจอ": 1100}[tall]

    st.caption(
        f"หน้า {here + 1} จาก {len(keys)} ในเอกสารนี้ · "
        f"แสดง {len(chosen)} จาก {len(all_engines)} engine"
    )

    image_path = IMAGE_DIR / f"{picked.page_id}.png"
    if not image_path.exists():
        st.error(f"ไม่พบไฟล์ภาพ {image_path.name}")
        return

    unstable_banner(picked)

    entry = truth.get(picked.page_id)
    truth_lines = entry.lines if entry else []
    if not truth_lines:
        st.info(
            "หน้านี้ยังไม่มีเฉลย จึงไม่มีคะแนน — เทียบข้อความกับภาพด้วยตาได้ "
            "หรือไปสร้างเฉลยที่แท็บ 'ทำเฉลย'"
        )
    engines = [
        _engine_record(name, results.get(name, {}).get(picked.page_id), truth_lines)
        for name in chosen
    ]
    engines = [e for e in engines if e is not None]

    image_uri, img_w, img_h = cached_image(image_path)
    st.components.v1.html(
        build_html(
            image_uri=image_uri,
            image_w=img_w,
            image_h=img_h,
            page_title=page_label(picked),
            truth_lines=truth_lines,
            engines=engines,
            height=height,
        ),
        height=height + 12,
        scrolling=False,
    )

    edit_panel(picked, chosen, results)
    page_round_history(picked.page_id)


def unstable_banner(picked: PageInfo) -> None:
    """เตือนตรงหัวหน้าว่าบรรทัดไหน engine เองก็ไม่มั่นใจ

    วางไว้เหนือตัวดูภาพเพื่อให้เห็นก่อนเริ่มไล่อ่าน — ถ้าไปอยู่ท้ายหน้า
    คนจะอ่านผ่านทั้งหน้าไปแล้วค่อยเจอ ซึ่งช้ากว่าที่ควรเป็น

    ข้อมูลมาจาก rescue.py --samples N (อ่านซ้ำหลายรอบแบบสุ่มแล้วตอบไม่ตรงกัน)
    หน้าที่ยังไม่เคยรันจะไม่ขึ้นอะไรเลย ไม่ใช่ขึ้นว่า "ปลอดภัย" เพราะยังไม่ได้ตรวจ
    ไม่เท่ากับตรวจแล้วไม่เจอ
    """
    points = unstable_points(picked.page_id)
    if not points:
        return

    st.warning(
        f"⚠️ หน้านี้มี {len(points)} จุดที่ engine อ่านซ้ำแล้วตอบไม่ตรงกัน — "
        "ควรดูภาพจริงตรงจุดพวกนี้ก่อน"
    )
    for p in points:
        with st.expander(f"บรรทัดที่ {p['grid_line'] + 1} · กางดูทุกรอบ"):
            for j, v in enumerate(p.get("variants") or [], 1):
                st.code(f"รอบ {j}: {v}")
            if p.get("box"):
                # ต้องเป็นภาพชุดเดียวกับที่ส่งเข้า engine ตอนอ่านซ้ำ ไม่ใช่ครอปย่อ
                # ไม่งั้นคนตรวจเห็นภาพชัดกว่าที่ engine เห็นจริง แล้วสรุปผิด
                uri = rescue_crop_uri(
                    str(IMAGE_DIR / f"{picked.page_id}.png"), tuple(p["box"])
                )
                if uri:
                    st.markdown(
                        f'<img src="{uri}" style="width:100%;border-radius:.5rem;'
                        f'border:1px solid var(--border)">',
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"ภาพที่ engine เห็นตอนอ่านซ้ำ — ครอปบรรทัดนี้แล้วขยาย {ZOOM} เท่า"
                    )


def edit_panel(picked: PageInfo, chosen: list[str], results: dict) -> None:
    """แก้ข้อความของหน้านี้เป็น markdown ได้เลยโดยไม่ต้องออกจากแท็บ

    ตัวดูด้านบนเป็น HTML component ก้อนเดียวซึ่งแก้ในตัวมันไม่ได้
    (ต้องส่งค่ากลับมาฝั่ง Python ซึ่ง component แบบฝัง html ทำไม่ได้)
    จึงวางช่องแก้ไว้ใต้ตัวดูแทน — ยังเห็นภาพต้นฉบับอยู่ในจอเดียวกัน

    เก็บเป็นไฟล์รายหน้าใน exports/pages/ แล้วตอนส่งออกทั้งเอกสารจากแท็บ
    markdown จะหยิบฉบับที่แก้ไว้ไปใช้แทนผลดิบให้เอง
    """
    with st.expander("✏️ แก้ข้อความหน้านี้เป็น markdown", expanded=False):
        usable = [
            n for n in chosen
            if (sp := results.get(n, {}).get(picked.page_id)) and sp.ok and sp.lines
        ]
        if not usable:
            st.info("ยังไม่มี engine ตัวไหนอ่านหน้านี้ได้")
            return

        engine = st.selectbox(
            "แก้จากผลของ engine",
            usable,
            key=f"md_edit_engine·{picked.page_id}",
            help="เลือกตัวที่อ่านได้ดีที่สุดมาเป็นตัวตั้งต้น จะได้แก้น้อยที่สุด",
        )

        raw = "\n".join(results[engine][picked.page_id].lines)
        saved = markdown_out.load_page(picked.page_id, engine)
        if saved is not None:
            st.success("หน้านี้แก้ไว้แล้ว — ด้านล่างคือฉบับที่แก้")
        else:
            st.caption("ยังไม่เคยแก้หน้านี้ — ด้านล่างคือผลดิบจาก OCR")

        # key ผูกกับหน้า+engine ไม่งั้นสลับหน้าแล้ว Streamlit จำข้อความเดิมไว้
        # ผู้ใช้จะเห็นของหน้าก่อนค้างอยู่แล้วเผลอกดบันทึกทับหน้าใหม่
        text = st.text_area(
            "markdown (แก้ได้)",
            value=saved if saved is not None else raw,
            height=320,
            key=f"md_edit_text·{picked.page_id}·{engine}",
            label_visibility="collapsed",
        )

        act = st.columns([1, 1, 2])
        if act[0].button("บันทึก", type="primary", key=f"md_save·{picked.page_id}"):
            markdown_out.save_page(picked.page_id, engine, text)
            st.success("บันทึกแล้ว — จะถูกใช้แทนผลดิบตอนส่งออกทั้งเอกสาร")
            st.rerun()

        if saved is not None and act[1].button(
            "ทิ้งที่แก้", key=f"md_reset·{picked.page_id}"
        ):
            markdown_out.clear_page(picked.page_id, engine)
            st.session_state.pop(f"md_edit_text·{picked.page_id}·{engine}", None)
            st.rerun()

        act[2].caption(
            f"{len([ln for ln in text.splitlines() if ln.strip()])} บรรทัด · "
            f"{len(text)} ตัวอักษร"
        )

        if text != raw:
            with st.popover("ดูตัวอย่างที่ render แล้ว"):
                st.markdown(text)


def text_stats(lines: list[str]) -> dict:
    """ตัวเลขสรุปของข้อความหนึ่งชุด — ตัวที่งานนี้สนใจจริงคือเลขไทย"""
    text = "".join(lines)
    return {
        "lines": len(lines),
        "chars": len(text),
        "thai_digits": sum(text.count(d) for d in THAI_DIGITS),
        "arabic_digits": sum(text.count(d) for d in "0123456789"),
    }


def diff_note(current: list[str], previous: list[str] | None) -> str:
    """ต่างจากรอบก่อนแค่ไหน — เทียบหลัง normalize เพื่อไม่ให้ช่องว่างนับเป็นความต่าง"""
    if previous is None:
        return "รอบแรกของ engine นี้"
    from rapidfuzz.distance import Levenshtein

    a, b = normalize("\n".join(current)), normalize("\n".join(previous))
    if a == b:
        return "เหมือนรอบก่อนทุกตัวอักษร"
    sim = Levenshtein.normalized_similarity(a, b)
    return f"ต่างจากรอบก่อน {1 - sim:.1%}"


def page_round_history(page_id: str) -> None:
    """ประวัติการอ่านหน้านี้ทีละรอบ

    วางไว้ใต้ split view ไม่ยัดเข้าไปในนั้น เพราะ component ข้างบนออกแบบมา
    สำหรับเทียบผลล่าสุดกับภาพ ส่วนตรงนี้คือเทียบรอบต่อรอบ คนละคำถามกัน

    ต้องบอกให้ครบว่า "รอบนั้นใช้อะไรอ่าน แล้วได้อะไรมา" ไม่ใช่พ่นข้อความดิบ
    เพราะพอมีหลายรอบแล้วจำไม่ได้ว่ารอบไหนใช้ภาพลบลายน้ำ รอบไหนใช้ภาพดิบ
    """
    rows = history.load_page(page_id)
    if not rows:
        with st.expander("ประวัติการอ่านหน้านี้"):
            st.caption(
                "ยังไม่มีประวัติของหน้านี้ — เริ่มบันทึกตั้งแต่รอบถัดไปที่กดสแกน "
                "ผลที่เห็นข้างบนมาจาก `ocr_results.json` ซึ่งเก็บแค่ผลล่าสุด"
            )
        return

    order = history.run_order()
    runs_meta = {r.get("started_at"): r for r in history.load()}

    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)

    # ผลรอบก่อนหน้าของ engine เดียวกัน ใช้ตอบว่า "รอบนี้ต่างจากรอบก่อนไหม"
    # rows เรียงใหม่ไปเก่า จึงต้องไล่จากท้ายมาหน้าเพื่อให้ "ก่อนหน้า" ถูกต้อง
    previous: dict[tuple[str, str], list[str]] = {}
    seen: dict[str, list[str]] = {}
    for r in reversed(rows):
        key = (r["run"], r["engine"])
        if r["engine"] in seen:
            previous[key] = seen[r["engine"]]
        seen[r["engine"]] = r["lines"]

    with st.expander(f"ประวัติการอ่านหน้านี้ — {len(by_run)} รอบ", expanded=False):
        labels = {}
        for run in by_run:  # rows เรียงล่าสุดก่อนอยู่แล้ว dict จึงคงลำดับนั้น
            no = order.get(run)
            stamp = run.replace("T", " ").replace("+00:00", "")[5:16]
            labels[f"รอบที่ {no or '?'} · {stamp} · {len(by_run[run])} engine"] = run

        pick = st.radio(
            "เลือกรอบ", list(labels), horizontal=False, label_visibility="collapsed"
        )
        run_key = labels[pick]
        chosen = by_run[run_key]
        meta = runs_meta.get(run_key, {})

        # หัวข้อรอบ — บอกว่าใช้อะไรอ่าน
        source = "ภาพลบลายน้ำ (`data/cleaned`)" if meta.get("clean") else "ภาพดิบ (`data/images`)"
        bits = [f"**ใช้** {source}"]
        if meta.get("redo"):
            bits.append("**อ่านใหม่ทับของเก่า**")
        if meta.get("duration_s"):
            bits.append(f"**รอบนี้ใช้เวลารวม** {meta['duration_s'] / 60:.1f} นาที")
        if meta.get("pages"):
            ran = len([e for e in meta.get("engines", []) if not e.get("skipped")])
            bits.append(f"**ทั้งรอบ** {ran} engine × {meta['pages']} หน้า")
        st.markdown(" &nbsp;·&nbsp; ".join(bits))

        table = []
        for r in chosen:
            s = text_stats(r["lines"])
            table.append(
                {
                    "engine": r["engine"],
                    "บรรทัด": s["lines"],
                    "ตัวอักษร": f"{s['chars']:,}",
                    "เลขไทย": s["thai_digits"],
                    "เลขอารบิก": s["arabic_digits"],
                    "วินาที": f"{r['ms'] / 1000:.1f}",
                    "เทียบรอบก่อน": diff_note(
                        r["lines"], previous.get((r["run"], r["engine"]))
                    ),
                    "สถานะ": "เสร็จ" if r["ok"] else f"พัง: {r.get('error')}",
                }
            )
        st.dataframe(table, width="stretch", hide_index=True)
        st.caption(
            "เลขอารบิกในเอกสารเลขไทยคืออาการอ่านผิดที่งานนี้วัดโดยตรง "
            "ตัวเลขสองคอลัมน์นี้จึงบอกได้เร็วกว่าอ่านข้อความเอง"
        )

        for r in chosen:
            s = text_stats(r["lines"])
            head = (
                f"{r['engine']} — {s['lines']} บรรทัด · {s['chars']:,} ตัวอักษร"
                f" · เลขไทย {s['thai_digits']}"
            )
            with st.expander(head):
                st.code("\n".join(r["lines"]) or "(ไม่มีข้อความ)")


