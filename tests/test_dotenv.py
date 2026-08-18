"""เทสต์ตัวอ่านไฟล์ .env

สำคัญพอที่ต้องมีเทสต์ เพราะถ้าอ่านค่าว่างเป็นสตริงว่างแทนที่จะเป็น "ยังไม่ตั้ง"
engine จะรายงานว่าพร้อมใช้แล้วไปพังตอนเรียก API แทนที่จะบอกตั้งแต่แรก
"""

from __future__ import annotations

import os

import thai_ocr_bench


def _run(tmp_path, body: str, keys: list[str]):
    env = tmp_path / ".env"
    env.write_text(body, encoding="utf-8")
    for k in keys:
        os.environ.pop(k, None)
    try:
        thai_ocr_bench._load_dotenv(env)
        return {k: os.environ.get(k) for k in keys}
    finally:
        for k in keys:
            os.environ.pop(k, None)


class TestLoadDotenv:
    def test_reads_plain_value(self, tmp_path):
        assert _run(tmp_path, "T_A=hello\n", ["T_A"])["T_A"] == "hello"

    def test_empty_value_counts_as_unset(self, tmp_path):
        # บรรทัดที่ค้างไว้ในไฟล์ตัวอย่างต้องไม่ทำให้ engine คิดว่าพร้อมใช้
        assert _run(tmp_path, "T_B=\n", ["T_B"])["T_B"] is None

    def test_comments_and_blanks_ignored(self, tmp_path):
        body = "# comment\n\n  # อีกอัน\nT_C=value\n"
        assert _run(tmp_path, body, ["T_C"])["T_C"] == "value"

    def test_quotes_stripped(self, tmp_path):
        out = _run(tmp_path, 'T_D="quoted"\nT_E=\'single\'\n', ["T_D", "T_E"])
        assert out["T_D"] == "quoted"
        assert out["T_E"] == "single"

    def test_value_with_equals_kept_whole(self, tmp_path):
        # คีย์ base64 มักลงท้ายด้วย = ต้องไม่ถูกตัด
        assert _run(tmp_path, "T_F=abc=def==\n", ["T_F"])["T_F"] == "abc=def=="

    def test_real_env_wins(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("T_G=from_file\n", encoding="utf-8")
        os.environ["T_G"] = "from_system"
        try:
            thai_ocr_bench._load_dotenv(env)
            assert os.environ["T_G"] == "from_system"
        finally:
            os.environ.pop("T_G", None)

    def test_missing_file_is_fine(self, tmp_path):
        thai_ocr_bench._load_dotenv(tmp_path / "ไม่มีไฟล์นี้")
