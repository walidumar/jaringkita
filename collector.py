"""
collector.py
Membuat instance perangkat (router & switch, opsional) dari konfigurasi .env,
dan menyediakan fungsi bantu lintas-perangkat:
- pembacaan trafik instan (Kbps) lewat monitor-traffic - untuk grafik realtime
- status seluruh interface (running/disabled) - untuk panel Dashboard

VLAN TIDAK di-hardcode di sini lagi - lihat vlan_registry.py untuk deteksi
otomatis VLAN dari router.
"""

import os
from dotenv import load_dotenv
from device import MikroTikDevice, RouterConnectionError  # noqa: F401 (re-export)

load_dotenv()

# ---------------------------------------------------------------------------
# Konfigurasi protokol koneksi.
# RouterOS < 7.9: REST API HANYA bisa diakses lewat HTTPS (www-ssl).
# RouterOS >= 7.9: HTTP (www) juga didukung.
# Default: HTTPS dengan verifikasi sertifikat dimatikan (sertifikat self-signed
# di jaringan lokal/lab adalah hal yang wajar).
# ---------------------------------------------------------------------------
_USE_HTTPS = os.getenv("USE_HTTPS", "true").strip().lower() != "false"
_VERIFY_SSL = os.getenv("VERIFY_SSL", "false").strip().lower() == "true"

# ---------------------------------------------------------------------------
# Instance perangkat
# ---------------------------------------------------------------------------
router = MikroTikDevice(
    name="Router",
    ip=os.getenv("ROUTER_IP", "192.168.88.1"),
    user=os.getenv("ROUTER_USER", "admin"),
    password=os.getenv("ROUTER_PASS", ""),
    use_https=_USE_HTTPS,
    verify_ssl=_VERIFY_SSL,
)

_switch_ip = os.getenv("SWITCH_IP", "").strip()
switch = None
if _switch_ip:
    switch = MikroTikDevice(
        name="Switch",
        ip=_switch_ip,
        user=os.getenv("SWITCH_USER", os.getenv("ROUTER_USER", "admin")),
        password=os.getenv("SWITCH_PASS", os.getenv("ROUTER_PASS", "")),
        use_https=_USE_HTTPS,
        verify_ssl=_VERIFY_SSL,
    )

# Nama interface fisik untuk uplink internet & trunk ke switch.
# Ini bukan VLAN (jadi tetap dikonfigurasi manual di .env) - sesuaikan dengan
# topologi Anda.
WAN_INTERFACE_NAME = os.getenv("WAN_INTERFACE_NAME", "ether1")
TRUNK_INTERFACE_NAME = os.getenv("TRUNK_INTERFACE_NAME", "ether5")


# ---------------------------------------------------------------------------
# Trafik realtime (monitor-traffic)
# ---------------------------------------------------------------------------
def get_interface_traffic_kbps(device: MikroTikDevice, interface_name: str) -> dict:
    """
    Trafik instan (Kbps) untuk satu interface, lewat 'interface monitor-traffic'.
    Mengembalikan ok=False (bukan exception) kalau gagal, supaya UI tetap bisa
    menampilkan pesan yang jelas tanpa merusak alur halaman.
    """
    try:
        data = device.monitor_traffic(interface_name)
    except RouterConnectionError:
        return {"rx_kbps": 0.0, "tx_kbps": 0.0, "ok": False, "raw": {}}

    rx_bps = float(data.get("rx-bits-per-second", 0) or 0)
    tx_bps = float(data.get("tx-bits-per-second", 0) or 0)
    return {
        "rx_kbps": round(rx_bps / 1000, 1),
        "tx_kbps": round(tx_bps / 1000, 1),
        "ok": True,
        "raw": data,
    }


def get_wan_trunk_traffic() -> dict:
    """Trafik instan untuk interface WAN (internet) dan trunk (ke switch)."""
    result = {}
    for key, iface_name in (("wan", WAN_INTERFACE_NAME), ("trunk", TRUNK_INTERFACE_NAME)):
        result[key] = {"name": iface_name, **get_interface_traffic_kbps(router, iface_name)}
    return result


# ---------------------------------------------------------------------------
# Status seluruh interface (untuk panel "interface yang running" di Dashboard)
# ---------------------------------------------------------------------------
def get_running_interfaces(device: MikroTikDevice) -> list[dict]:
    """Daftar SEMUA interface pada satu perangkat beserta status running/disabled."""
    try:
        interfaces = device.get_interfaces()
    except RouterConnectionError:
        return []

    result = []
    for i in interfaces:
        result.append(
            {
                "name": i.get("name", "?"),
                "type": i.get("type", "?"),
                "running": str(i.get("running", "false")).lower() == "true",
                "disabled": str(i.get("disabled", "false")).lower() == "true",
                "comment": i.get("comment", ""),
            }
        )
    return result


def get_running_interfaces_with_traffic(device: MikroTikDevice) -> list[dict]:
    """
    Sama seperti get_running_interfaces(), tapi tiap interface yang sedang
    running ditambahi statistik trafik instan (Kbps) lewat monitor-traffic.
    Dipakai untuk panel "Status Interface" yang diperbarui realtime setiap
    beberapa detik. Interface yang down/disabled tidak dicek trafiknya
    (rx_kbps/tx_kbps = None) supaya tidak membuang waktu pengujian.
    """
    interfaces = get_running_interfaces(device)
    result = []
    for iface in interfaces:
        entry = dict(iface)
        if iface["running"] and not iface["disabled"]:
            traffic = get_interface_traffic_kbps(device, iface["name"])
            entry["rx_kbps"] = traffic["rx_kbps"] if traffic["ok"] else None
            entry["tx_kbps"] = traffic["tx_kbps"] if traffic["ok"] else None
        else:
            entry["rx_kbps"] = None
            entry["tx_kbps"] = None
        result.append(entry)
    return result


def get_ip_address_table(device: MikroTikDevice) -> list[dict]:
    """
    Detail IP address yang di-assign ke SETIAP interface (fisik maupun VLAN),
    langsung dari /ip/address - untuk menu "cek detail IP per interface".
    """
    try:
        addresses = device.get_ip_addresses()
    except RouterConnectionError:
        return []

    result = []
    for a in addresses:
        result.append(
            {
                "interface": a.get("interface", "?"),
                "address": a.get("address", "?"),
                "network": a.get("network", "-"),
                "disabled": str(a.get("disabled", "false")).lower() == "true",
                "comment": a.get("comment", "-") or "-",
            }
        )
    return result


def get_dhcp_leases_grouped(device: MikroTikDevice = None) -> dict:
    """
    Mengelompokkan DHCP lease berdasarkan nama DHCP server (pool), lengkap
    dengan daftar client aktif per pool (IP address, MAC, hostname, sisa waktu
    lease) - untuk panel "jumlah & daftar client per DHCP server pool" di
    Dashboard. Memisahkan per server/pool supaya jelas berapa client di tiap
    pool (mis. dhcp-siswa vs dhcp-guru), bukan digabung jadi satu angka total.

    Return: dict {nama_server: {"count_active": N, "total": M, "leases": [ {...}, ... ]}}
    """
    device = device or router
    try:
        leases = device.get_dhcp_leases()
    except RouterConnectionError:
        return {}

    grouped: dict = {}
    for lease in leases:
        server = lease.get("server", "unknown")
        grouped.setdefault(server, {"count_active": 0, "total": 0, "leases": []})

        status = lease.get("status", "?")
        grouped[server]["leases"].append(
            {
                "IP Address": lease.get("address", "?"),
                "MAC Address": lease.get("mac-address", "?"),
                "Hostname": lease.get("host-name", "-") or "-",
                "Lease Time": lease.get("expires-after", "-") or "-",
                "Status": status,
            }
        )
        grouped[server]["total"] += 1
        if status == "bound":
            grouped[server]["count_active"] += 1

    return grouped
