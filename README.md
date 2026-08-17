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
.venv\Scripts\python.exe render_pages.py     # PDF -> PNG 300 DPI (เคารพ /Rotate)
.venv\Scripts\python.exe build_truth.py      # ดึงเฉลยจาก text layer
.venv\Scripts\python.exe smoke.py <page_id>  # ทดสอบ engine หน้าเดียว
```

## โครงสร้าง

| ไฟล์ | หน้าที่ |
| --- | --- |
| `src/thai_ocr_bench/thai_text.py` | จัดข้อความไทยให้เป็นรูปมาตรฐานก่อนวัด |
| `src/thai_ocr_bench/metrics.py` | CER, ความแม่นรายชนิดอักขระ, จับคู่บรรทัด, ไฮไลต์จุดผิด |
| `src/thai_ocr_bench/render.py` | แปลง PDF เป็นภาพ พร้อมจัดการ `/Rotate` |
| `src/thai_ocr_bench/truth.py` | เฉลย — ดึงจาก text layer หรือคนพิมพ์เอง |
| `src/thai_ocr_bench/versions.py` | บันทึกเวอร์ชันติดไปกับผล |
| `src/thai_ocr_bench/engines/` | หนึ่งไฟล์ = หนึ่ง OCR |

## OCR ที่เทียบ

| ชื่อ | โมเดล | หมายเหตุ |
| --- | --- | --- |
| `tesseract-tha` | Tesseract 5.4 + `tha` (tessdata_best) | เส้นฐานคลาสสิก รันบน CPU |
| `paddle-th` | `th_PP-OCRv5_mobile_rec` | dict มีเลขไทยครบ ๐–๙ |
| `easyocr-th` | `thai_g1` | **ตัวคุม** — charset ไม่มี `๐` |
| `surya` | Surya OCR | มี layout analysis |
| `typhoon-2b` | `typhoon-ai/typhoon-ocr1.5-2b` | VLM · ย่อภาพเหลือ 1536 px เพราะ VRAM 6 GB |
| `thai-trocr` | `kkatiz/thai-trocr-thaigov-v2` | เทรนบน ThaiGov V2 Corpus · ต้องยืมตัวตรวจจับของ Paddle |

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
