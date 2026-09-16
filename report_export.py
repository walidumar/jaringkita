"""
report_export.py
Mengubah hasil pengujian (evidence) + hasil analisis AI menjadi file yang bisa
diunduh langsung dari dashboard (PDF & CSV) - supaya hasil analisis tidak
cuma tampil sekali di layar lalu hilang, tapi terdokumentasi dan bisa
dilampirkan sebagai bukti pendukung.
"""

import csv
import io
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

APP_NAME = "JaringKita"
APP_TAGLINE = "AI Network Monitoring & Diagnostic Assistant"

# Karakter umum di luar Latin-1 (font dasar FPDF) diganti dulu supaya PDF
# tidak error saat ada tanda baca "pintar" dari hasil teks AI.
_CHAR_REPLACEMENTS = {
    "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
}


def _sanitize(text: str) -> str:
    text = str(text)
    for old, new in _CHAR_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def _flatten(data: dict, prefix: str = "") -> list:
    """Meratakan dict (termasuk nested dict/list) jadi pasangan (key, value) untuk CSV/PDF."""
    rows = []
    for k, v in data.items():
        label = f"{prefix}{k}"
        if isinstance(v, dict):
            rows.extend(_flatten(v, prefix=f"{label}."))
        elif isinstance(v, list):
            rows.append((label, "; ".join(str(x) for x in v) if v else "-"))
        else:
            rows.append((label, "-" if v is None else str(v)))
    return rows


def build_csv_bytes(meta: dict, ai_text: str = "") -> bytes:
    """Menghasilkan file CSV (2 kolom: Field, Value) dari data laporan + hasil AI."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Field", "Value"])
    writer.writerow(["Aplikasi", f"{APP_NAME} - {APP_TAGLINE}"])
    writer.writerow(["Waktu Ekspor", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    for key, value in _flatten(meta):
        writer.writerow([key, value])
    if ai_text:
        writer.writerow(["Analisis & Rekomendasi AI", ai_text])
    # BOM (utf-8-sig) supaya Excel langsung baca UTF-8 dengan benar, bukan karakter aneh.
    return buffer.getvalue().encode("utf-8-sig")


def build_pdf_bytes(title: str, meta: dict, ai_text: str = "") -> bytes:
    """Menghasilkan file PDF ringkas: judul laporan, data pengujian, dan hasil AI."""
    pdf = FPDF()
    pdf.add_page()

    def line(text: str, size: int = 9, bold: bool = False, gap_after: float = 0):
        """Cetak satu blok teks lalu SELALU reset kursor ke margin kiri baris baru -
        fpdf2 versi baru tidak melakukan ini otomatis seperti versi lama, dan
        kalau tidak di-reset, baris berikutnya bisa kehabisan ruang horizontal."""
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(0, 6, _sanitize(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if gap_after:
            pdf.ln(gap_after)

    line(APP_NAME, size=16, bold=True)
    line(APP_TAGLINE, size=10, gap_after=4)

    line(title, size=13, bold=True)
    line(f"Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", size=9, gap_after=3)

    line("Data Pengujian", size=11, bold=True)
    for key, value in _flatten(meta):
        line(f"{key}: {value}", size=9)
    pdf.ln(3)

    if ai_text:
        line("Hasil Analisis & Rekomendasi AI", size=11, bold=True)
        line(ai_text, size=9)

    raw = pdf.output()
    return bytes(raw)


def render_download_buttons(st_module, report_title: str, meta: dict, ai_text: str, file_prefix: str):
    """
    Helper untuk dipanggil dari app.py: menampilkan 2 tombol download (PDF & CSV)
    berdampingan. st_module = modul streamlit (dioper supaya file ini tidak
    perlu import streamlit langsung, tetap fokus pada logika pembuatan file).
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_bytes = build_pdf_bytes(report_title, meta, ai_text)
    csv_bytes = build_csv_bytes(meta, ai_text)

    col1, col2 = st_module.columns(2)
    col1.download_button(
        "📄 Download Laporan (PDF)",
        data=pdf_bytes,
        file_name=f"{file_prefix}_{ts}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    col2.download_button(
        "📊 Download Data (CSV)",
        data=csv_bytes,
        file_name=f"{file_prefix}_{ts}.csv",
        mime="text/csv",
        use_container_width=True,
    )
