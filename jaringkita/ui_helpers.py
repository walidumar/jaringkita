"""
ui_helpers.py
Kumpulan fungsi bantu tampilan yang dipakai berulang di beberapa halaman:
- inject_right_sidebar_css: memindahkan posisi sidebar (menu vertikal) ke kanan
- status_badge: label status yang ramah-baca (bukan istilah teknis mentah)
- render_ai_result: kotak styling untuk menampilkan hasil analisis AI
"""

import streamlit as st


def inject_right_sidebar_css():
    """
    Streamlit secara default meletakkan sidebar di kiri. CSS ini membalik
    urutan flex container utama supaya sidebar tampil di sebelah KANAN,
    sesuai permintaan tampilan menu vertikal di kanan.
    """
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            display: flex;
            flex-direction: row;
        }
        [data-testid="stAppViewContainer"] > section.main {
            order: 1;
        }
        section[data-testid="stSidebar"] {
            order: 2;
            border-left: 1px solid rgba(49, 51, 63, 0.2);
            border-right: none;
        }
        /* Perbaikan kecil supaya tombol collapse sidebar tetap terlihat wajar */
        [data-testid="collapsedControl"] {
            left: unset;
            right: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    """Mengubah kode status teknis (HEALTHY/DEGRADED/DOWN/TIDAK DIUJI) jadi label ramah-baca."""
    mapping = {
        "HEALTHY": "🟢 Normal",
        "DEGRADED": "🟡 Terganggu Sebagian",
        "DOWN": "🔴 Bermasalah",
        "TIDAK DIUJI": "⚪ Belum Ada Pengujian",
    }
    return mapping.get(status, f"⚪ {status}")


def render_ai_result(text: str):
    """
    Menampilkan hasil analisis AI dalam kotak yang menonjol dan mudah dibaca.
    Warna latar DAN warna teks di-set eksplisit (bukan mengandalkan warna
    default tema Streamlit) supaya kontras tetap terjaga baik di tema terang
    maupun gelap - sebelumnya teks bisa nyaris tidak terbaca di tema gelap
    karena warna teks mengikuti tema (putih) di atas latar terang.
    """
    st.markdown(
        f"""
        <div style="
            background-color:#eef3fc;
            color:#1a2740;
            padding:18px 20px;
            border-radius:10px;
            border-left:5px solid #4c8bf5;
            line-height:1.6;
            font-size:0.98rem;
        ">
        {text}
        </div>
        """,
        unsafe_allow_html=True,
    )
