"""
evidence.py
Menggabungkan hasil pengujian aktif menjadi satu struktur "evidence" yang
konsisten, mengevaluasi status (HEALTHY/DEGRADED/DOWN/TIDAK DIUJI) berdasarkan
rule sederhana (BUKAN AI), dan menyediakan versi "human friendly" untuk UI.

Pengujian sekarang FLEKSIBEL: bisa ICMP saja, TCP saja, atau keduanya - sesuai
pilihan sysadmin di menu VLAN Health. Field placeholder 'gateway_reachable'/
'route_exists' yang dulu selalu True (tidak pernah benar-benar diuji) sudah
DIHAPUS - supaya evidence yang dikirim ke AI hanya berisi data yang benar-benar
diukur, bukan asumsi yang disamarkan sebagai fakta.
"""

from datetime import datetime
from active_test import ping_test_verbose, tcp_port_test


def evaluate_status(checks: dict) -> tuple[str, bool]:
    """
    Rule sederhana untuk menentukan status berdasarkan hasil pengujian yang
    BENAR-BENAR dijalankan (bisa jadi cuma ICMP, cuma TCP, atau keduanya).
    Mengembalikan (status, anomaly_detected).
    """
    icmp = checks.get("icmp_reachable")  # True / False / None (tidak diuji)
    tcp = checks.get("tcp_reachable")    # True / False / None (tidak diuji)

    if icmp is False:
        return "DOWN", True
    if tcp is False:
        return "DEGRADED", True
    if icmp is True or tcp is True:
        return "HEALTHY", False
    return "TIDAK DIUJI", False


def build_evidence(
    source_vlan,
    dest_vlan,
    dest_ip: str,
    dest_port: int = 443,
    test_icmp: bool = True,
    test_tcp: bool = True,
) -> dict:
    """
    Membangun evidence untuk satu pengujian konektivitas.
    source_vlan/dest_vlan hanya dipakai sebagai label konteks (boleh None kalau
    target bukan bagian dari VLAN yang terdeteksi, mis. IP internet).

    Pengujian ICMP memakai ping_test_verbose() (bukan sekadar True/False) supaya
    output mentah ping (latency, TTL, dst) bisa ditampilkan di UI sebagai bukti
    nyata bahwa protokol ICMP benar-benar dijalankan, bukan diasumsikan.
    """
    icmp_raw_output = ""
    icmp_ok = None
    if test_icmp:
        icmp_result = ping_test_verbose(dest_ip)
        icmp_ok = icmp_result["success"]
        icmp_raw_output = icmp_result["raw_output"]

    tcp_ok = tcp_port_test(dest_ip, dest_port) if test_tcp else None

    checks = {
        "icmp_reachable": icmp_ok,
        "icmp_tested": test_icmp,
        "icmp_raw_output": icmp_raw_output,
        "tcp_reachable": tcp_ok,
        "tcp_tested": test_tcp,
        "tested_port": dest_port if test_tcp else None,
    }

    status, anomaly = evaluate_status(checks)

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source_vlan": source_vlan,
        "destination_vlan": dest_vlan,
        "destination_ip": dest_ip,
        "checks": checks,
        "status": status,
        "anomaly_detected": anomaly,
    }


def humanize_checks(checks: dict) -> list[str]:
    """
    Mengubah evidence mentah menjadi daftar kalimat yang mudah dibaca sysadmin -
    HANYA menampilkan hasil pengujian yang benar-benar dijalankan.
    """
    lines = []

    if checks.get("icmp_tested", True):
        icmp = checks.get("icmp_reachable")
        lines.append("Ping (ICMP) berhasil" if icmp else "Ping (ICMP) GAGAL / timeout")

    if checks.get("tcp_tested", True):
        tcp = checks.get("tcp_reachable")
        port = checks.get("tested_port", "?")
        lines.append(
            f"Port {port} (TCP) dapat diakses" if tcp else f"Port {port} (TCP) TIDAK dapat diakses"
        )

    if not lines:
        lines.append("Tidak ada pengujian yang dijalankan - pilih minimal satu metode pengujian.")

    return lines
