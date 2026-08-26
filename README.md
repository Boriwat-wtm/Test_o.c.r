# thai-ocr-bench

เปรียบเทียบความแม่นของ OCR หลายตัวบนเอกสารภาษาไทยจริง โดยเน้นสามอย่างที่เอกสารไทยใช้ปนกันเสมอ — **อักษรไทย**, **เลขไทย ๐–๙** และ **เลขอารบิก**

## ทำไมต้องมีเครื่องมือนี้

CER ตัวเดียวหลอกได้ เลขไทยเป็นแค่ 2–3% ของตัวอักษรในหน้า ถ้าวัดรวม ๆ engine ที่อ่านเลขไทยผิดหมดก็ยังได้คะแนนสวย เครื่องมือนี้จึงแยกวัดความแม่นตามชนิดอักขระ และมีหน้าเว็บให้ตรวจผลทีละบรรทัดด้วยตา

## ติดตั้ง

ต้องมี [uv](https://github.com/astral-sh/uv), [Tesseract 5](https://github.com/UB-Mannheim/tesseract), [Poppler](https://github.com/oschwartz10612/poppler-windows)

```powershell
uv venv --python 3.12
uv pip install -e .
```

`tha.traineddata` จาก tessdata_best ต้องอยู่ใน `vendor/tessdata/`

## ใช้งาน

```powershell
.venv\Scripts\python.exe render_pages.py      # PDF -> PNG 300 DPI (เคารพ /Rotate)
.venv\Scripts\python.exe build_truth.py       # ดึงเฉลยจาก text layer
.venv\Scripts\python.exe clean_images.py      # ลบลายน้ำ เก็บที่ data/cleaned/
.venv\Scripts\python.exe run_bench.py         # รัน OCR ทุกตัว เก็บผลลงดิสก์
.venv\Scripts\streamlit.exe run app.py        # หน้าเว็บดูผล
```

สคริปต์เสริม

```powershell
.venv\Scripts\python.exe smoke.py <page_id>   # ทดสอบ engine หน้าเดียวก่อนรันเต็ม
.venv\Scripts\python.exe compare_engines.py   # ความแม่นแยกตามชนิดอักขระ + คู่ที่สับสน
.venv\Scripts\python.exe rescue.py --engine <engine>   # ครอปจุดน่าสงสัยแล้วอ่านซ้ำแบบซูม
.venv\Scripts\python.exe check_rescue.py      # ตัดสินว่าการอ่านซ้ำช่วยจริงไหม
```

## โครงสร้าง

| ไฟล์ | หน้าที่ |
| --- | --- |
| `src/thai_ocr_bench/thai_text.py` | จัดข้อความไทยให้เป็นรูปมาตรฐานก่อนวัด |
| `src/thai_ocr_bench/metrics.py` | CER, ความแม่นรายชนิดอักขระ, จับคู่บรรทัด, ไฮไลต์จุดผิด |
| `src/thai_ocr_bench/render.py` | แปลง PDF เป็นภาพ พร้อมจัดการ `/Rotate` |
| `src/thai_ocr_bench/truth.py` | เฉลย — ดึงจาก text layer หรือคนพิมพ์เอง |
| `src/thai_ocr_bench/versions.py` | บันทึกเวอร์ชันติดไปกับผล |
| `src/thai_ocr_bench/suspect.py` | หาจุดที่น่าจะอ่านผิดโดยไม่ต้องมีเฉลย |
| `src/thai_ocr_bench/markdown_out.py` | ส่งผลออกเป็น markdown ที่คนแก้ต่อได้ |
| `src/thai_ocr_bench/engines/` | หนึ่งไฟล์ = หนึ่ง OCR |
| `src/thai_ocr_bench/ui/` | หน้าเว็บ หนึ่งไฟล์ = หนึ่งแท็บ |
| `experiments/` | สคริปต์ทดลองครั้งเดียวจบ เก็บไว้เป็นหลักฐานว่าเคยวัดอะไรไปแล้ว |

## OCR ที่เทียบ

| ชื่อ | โมเดล | หมายเหตุ |
| --- | --- | --- |
| `tesseract-tha` | Tesseract 5.4 + `tha` (tessdata_best) | เส้นฐานคลาสสิก รันบน CPU |
| `paddle-th` | `th_PP-OCRv5_mobile_rec` | dict มีเลขไทยครบ ๐–๙ |
| `paddle-th-server` | ตัวเดิม + ตัวตรวจจับ `PP-OCRv5_server_det` | ตีกรอบดีกว่ามาก แต่ช้ากว่า ๑๕ เท่า (~๙ นาที/หน้า) |
| `easyocr-th` | `thai_g1` | **ตัวคุม** — charset ไม่มี `๐` |
| `surya` | Surya OCR | ยังใช้ไม่ได้ — ชนกับ transformers 5.x ที่ Typhoon ต้องใช้ |
| `typhoon-2b` | `typhoon-ai/typhoon-ocr1.5-2b` | VLM รันในเครื่อง · ย่อภาพเหลือ 1536 px เพราะ VRAM 6 GB |
| `typhoon-api` | `typhoon-ocr` ผ่าน opentyphoon.ai | รุ่น 2B ตัวเดียวกับข้างบน แต่ไม่กิน VRAM · ส่งเอกสารออกนอกเครื่อง |
| `typhoon-api-num` | ตัวเดิม + กำชับเรื่องเลขไทยในคำสั่ง | แยกเป็นคนละตัวเพื่อวัดว่าการกำชับช่วยจริงไหม |
| `thai-trocr` | `kkatiz/thai-trocr-thaigov-v2` | เทรนบน ThaiGov V2 Corpus · ต้องยืมตัวตรวจจับของ Paddle |
| `thai-trocr-openthaigpt` | `openthaigpt/thai-trocr` | 0.1B (ViT + Electra) · checkpoint คนละตัวบนสถาปัตยกรรมเดียวกัน |

เพิ่ม OCR ใหม่: สร้างไฟล์ในโฟลเดอร์ `engines/` สืบทอด `Engine` แล้วเรียก `register()`
ตัววัดผลกับหน้าเว็บไม่ต้องแก้

## วิธีวัดผล

วัดแบบจับคู่บรรทัด ไม่ใช่ต่อข้อความทั้งหน้าเป็นก้อนเดียว เพราะ OCR แต่ละตัวเรียงลำดับ
การอ่านต่างกัน และตัวที่อ่านลายน้ำหรือลายเซ็นเจอจะถูกลงโทษหนักเกินจริง
จึงแยกรายงานสามค่าที่ตีความต่างกัน

| ค่า | ตอบว่า |
| --- | --- |
| CER เฉพาะบรรทัดที่จับคู่ได้ | อ่านตัวอักษรแม่นแค่ไหน |
| recall | อ่านครบแค่ไหน |
| บรรทัดเกิน | พ่นสิ่งที่ไม่ควรเจอเท่าไร |

เลขไทยวัดสองแบบ — `strict` ต้องได้เลขไทยตรงตัว และ `lenient` แปลงเป็นเลขอารบิก
ทั้งสองฝั่งก่อนเทียบ ช่องว่างระหว่างสองค่านี้บอกว่าความผิดกู้คืนได้หรือไม่

## สิ่งที่ค้นพบระหว่างสร้าง

**หน้า PDF มีค่า `/Rotate` ต่างกัน (90° และ 270°)** ถ้าดึงภาพดิบออกมาโดยไม่อ่านค่านี้ ทุกหน้าจะเข้า OCR แบบตะแคง แล้วสรุปผิดว่า engine อ่านไทยไม่ได้ — `render.py` จัดการให้แล้ว

**text layer ของ PDF ที่สร้างจาก Word + THSarabunPSK แมปสระผิด** สระอา (า) ถูกดึงออกมาเป็นสระอำ (ำ) ทุกตัว ส่วนสระอำตัวจริงมีช่องว่างนำหน้า `truth.repair_sara()` ซ่อมให้ และมีเทสต์กำกับ

**Tesseract แทรกช่องว่างระหว่างตัวอักษรไทย** เช่น `ม ิ ต ิ ด ้ า น` การวัดจึงตัดช่องว่างทิ้งก่อนเสมอ

## ข้อมูลทดสอบ

เอกสารต้นฉบับไม่อยู่ใน repo นี้ (อาจมีข้อมูลส่วนบุคคล) ตั้ง path ผ่านตัวแปรแวดล้อม

```powershell
$env:THAI_OCR_SOURCE_DIR = "D:\path\to\documents"
```

## เทสต์

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```
