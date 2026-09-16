"""
vlan_registry.py
Deteksi VLAN secara OTOMATIS dari router lewat REST API (/interface/vlan +
/ip/address) - tidak ada VLAN yang di-hardcode di kode.

Label ramah-baca tiap VLAN diambil berurutan dari:
1. Override manual yang disimpan sysadmin lewat UI (vlan_labels.json)
2. Field 'comment' di MikroTik pada interface VLAN tsb (kalau sysadmin sudah
   mengisinya langsung di router)
3. Nama interface VLAN itu sendiri (fallback paling akhir)

Ini memenuhi kebutuhan "auto-detect, dengan minimal opsi pendaftaran manual" -
manual di sini HANYA untuk memberi label yang enak dibaca, bukan untuk
mendaftarkan keberadaan VLAN itu sendiri (itu selalu otomatis dari router).
"""

import json
import os

from device import RouterConnectionError

LABELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlan_labels.json")


def load_manual_labels() -> dict:
    if os.path.exists(LABELS_FILE):
        try:
            with open(LABELS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_manual_label(interface_name: str, label: str):
    labels = load_manual_labels()
    labels[interface_name] = label
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)


def get_detected_vlans(device) -> list[dict]:
    """
    Mengembalikan daftar VLAN yang BENAR-BENAR terdeteksi di perangkat,
    lengkap dengan label ramah-baca dan gateway/subnet (jika ada IP address
    yang di-assign ke interface VLAN tsb).

    Return: list of dict {name, vlan_id, label, parent_interface, cidr, gateway,
                           has_manual_label, has_comment}
    """
    try:
        raw_vlans = device.get_vlan_interfaces()
    except RouterConnectionError:
        return []

    try:
        ip_addresses = device.get_ip_addresses()
    except RouterConnectionError:
        ip_addresses = []

    ip_by_iface = {}
    for addr in ip_addresses:
        iface = addr.get("interface")
        if iface and iface not in ip_by_iface:
            ip_by_iface[iface] = addr.get("address", "")  # format "10.10.40.1/24"

    manual_labels = load_manual_labels()

    result = []
    for v in raw_vlans:
        name = v.get("name", "")
        vlan_id = v.get("vlan-id", "?")
        comment = (v.get("comment") or "").strip()
        manual = manual_labels.get(name, "")
        label = manual or comment or name
        cidr = ip_by_iface.get(name, "")
        gateway = cidr.split("/")[0] if cidr else ""

        result.append(
            {
                "name": name,
                "vlan_id": vlan_id,
                "label": label,
                "parent_interface": v.get("interface", "?"),
                "cidr": cidr,
                "gateway": gateway,
                "has_manual_label": bool(manual),
                "has_comment": bool(comment),
            }
        )

    try:
        result.sort(key=lambda x: int(x["vlan_id"]))
    except (ValueError, TypeError):
        pass

    return result


def get_vlan_client_counts_arp(device) -> dict:
    """
    Menghitung jumlah client per interface VLAN berdasarkan tabel ARP -
    mencakup client dengan IP statis maupun DHCP, tidak bergantung pada
    penamaan DHCP server tertentu.
    Return: dict {nama_interface: jumlah_client}
    """
    try:
        arp_entries = device.get_arp_table()
    except RouterConnectionError:
        return {}

    counts = {}
    for entry in arp_entries:
        iface = entry.get("interface")
        if iface and entry.get("mac-address"):
            counts[iface] = counts.get(iface, 0) + 1
    return counts
