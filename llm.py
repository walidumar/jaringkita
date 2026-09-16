"""
llm.py
Mengirim data (evidence konektivitas, ringkasan log, atau hasil ping/traceroute)
ke Ollama (model lokal) dan mengembalikan hasil analisis dalam SATU PARAGRAF
sederhana berbahasa Indonesia, dengan struktur STATUS / FAKTA / KESIMPULAN
(KESIMPULAN sudah menggabungkan inference, verifikasi, dan rekomendasi).

Prinsip penting: LLM HANYA menerima data yang sudah diringkas/diverifikasi oleh
modul lain (evidence.py, log_processor.py, active_test.py) - tidak pernah
diberi akses langsung ke MikroTik, dan tidak pernah mengubah konfigurasi apapun.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

SIMPLE_SYSTEM_PROMPT = """Kamu adalah asisten sysadmin jaringan yang menjelaskan kondisi
jaringan MikroTik kepada seorang admin sekolah dengan bahasa yang sederhana, jelas, dan lugas.

ATURAN KETAT:
1. Hanya gunakan data yang diberikan di pesan pengguna. Jangan mengarang kondisi,
   angka, atau kejadian yang tidak ada dalam data tersebut.
2. Jawab HANYA dalam SATU paragraf singkat (maksimal 5-6 kalimat), Bahasa Indonesia
   yang natural (bukan bahasa terjemahan kaku).
3. Format WAJIB persis seperti ini, sebagai satu paragraf yang mengalir (bukan bullet,
   bukan heading terpisah baris):

   STATUS: <satu kata/frasa pendek, mis. Normal / Terganggu Sebagian / Bermasalah>. FAKTA: <ringkasan fakta paling penting dari data, 1-2 kalimat>. KESIMPULAN: <penjelasan kemungkinan penyebab DAN rekomendasi tindakan yang lugas untuk sysadmin, digabung dalam 2-3 kalimat, langsung ke intinya>.

4. Jangan gunakan kalimat pembuka basa-basi seperti "Berikut adalah analisis...".
   Langsung mulai dengan "STATUS:".
"""


def _call_ollama(system_prompt: str, user_payload: dict) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
        ],
        "stream": False,
        "think": False,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def simple_analysis(data: dict) -> str:
    """
    Fungsi analisis AI generik dan seragam - dipakai untuk:
    - diagnosis evidence konektivitas antar-VLAN
    - analisis hasil ping/traceroute
    - analisis ringkasan log (error/warning/info)
    Semua menghasilkan format output yang sama: satu paragraf STATUS/FAKTA/KESIMPULAN.
    """
    return _call_ollama(SIMPLE_SYSTEM_PROMPT, data)


# Alias supaya nama fungsi tetap deskriptif di tempat pemanggilannya (app.py),
# meskipun secara teknis semuanya memanggil fungsi generik yang sama.
diagnose_connectivity = simple_analysis
analyze_ping_traceroute = simple_analysis
analyze_logs_simple = simple_analysis
