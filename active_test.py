"""
active_test.py
Pengujian aktif dari sisi laptop/PC yang menjalankan JaringKita:
- ping_test / ping_test_verbose (ICMP)
- tcp_port_test (TCP)
- traceroute_test (tracert/traceroute)

Catatan: pengujian dilakukan dari mesin yang menjalankan skrip ini. Pastikan
mesin tersebut terhubung ke segmen jaringan yang relevan dengan skenario yang
sedang didemonstrasikan.
"""

import platform
import socket
import subprocess


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def ping_test(target_ip: str, count: int = 2, timeout_s: int = 3) -> bool:
    """Versi ringkas: True jika target merespons ping."""
    return ping_test_verbose(target_ip, count=count, timeout_s=timeout_s)["success"]


def ping_test_verbose(target_ip: str, count: int = 4, timeout_s: int = 3) -> dict:
    """
    Versi lengkap ping - mengembalikan output mentah + status sukses/gagal,
    untuk ditampilkan di menu Diagnostic Tools.
    """
    if _is_windows():
        cmd = ["ping", "-n", str(count), "-w", str(timeout_s * 1000), target_ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout_s), target_ip]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s * count + 10
        )
        output = result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        output = "Ping melebihi batas waktu (timeout)."
    except FileNotFoundError:
        output = "Perintah ping tidak ditemukan di sistem ini."

    success = "ttl=" in output.lower()
    return {"raw_output": output, "success": success}


def tcp_port_test(target_ip: str, port: int, timeout: float = 3.0) -> bool:
    """Mengembalikan True jika koneksi TCP ke target_ip:port berhasil dibuka."""
    try:
        with socket.create_connection((target_ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def traceroute_test(target_ip: str, max_hops: int = 15, timeout_s: int = 2) -> str:
    """
    Menjalankan traceroute (Linux/Mac) atau tracert (Windows) dan mengembalikan
    output mentah sebagai teks.
    """
    if _is_windows():
        cmd = ["tracert", "-h", str(max_hops), "-w", str(timeout_s * 1000), target_ip]
    else:
        cmd = ["traceroute", "-m", str(max_hops), "-w", str(timeout_s), target_ip]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s * max_hops + 20
        )
        return result.stdout or result.stderr
    except FileNotFoundError:
        return (
            "Perintah traceroute/tracert tidak ditemukan di sistem ini. "
            "Di Linux, install dengan: sudo apt install traceroute"
        )
    except subprocess.TimeoutExpired:
        return "Traceroute melebihi batas waktu (timeout)."
