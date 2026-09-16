"""
device.py
Kelas MikroTikDevice membungkus komunikasi REST API ke SATU perangkat MikroTik.
Dengan pendekatan class ini, kode yang sama bisa dipakai untuk memonitor lebih
dari satu perangkat sekaligus (router DAN switch) tanpa duplikasi logic.

CATATAN PENTING (RouterOS < 7.9):
REST API di RouterOS versi sebelum 7.9 HANYA bisa diakses lewat HTTPS
(layanan www-ssl), BUKAN lewat HTTP biasa (layanan www) - baru mulai 7.9
akses HTTP didukung. Karena itu kelas ini memakai HTTPS secara default,
dengan verifikasi sertifikat dimatikan (verify=False) karena umumnya
memakai sertifikat self-signed di jaringan lab/sekolah.
"""

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

# Matikan warning "Unverified HTTPS request" - kita sudah sadar & sengaja
# memakai verify=False untuk sertifikat self-signed di jaringan lokal.
urllib3.disable_warnings(InsecureRequestWarning)


class RouterConnectionError(Exception):
    """Dilempar ketika perangkat MikroTik tidak bisa dihubungi / REST API gagal."""
    pass


class MikroTikDevice:
    def __init__(
        self,
        name: str,
        ip: str,
        user: str,
        password: str,
        timeout: int = 5,
        use_https: bool = True,
        verify_ssl: bool = False,
    ):
        self.name = name
        self.ip = ip
        self.auth = (user, password)
        self.timeout = timeout
        self.protocol = "https" if use_https else "http"
        self.verify_ssl = verify_ssl

    def _base_url(self, path: str) -> str:
        return f"{self.protocol}://{self.ip}/rest/{path}"

    def _get(self, path: str):
        url = self._base_url(path)
        try:
            resp = requests.get(
                url, auth=self.auth, timeout=self.timeout, verify=self.verify_ssl
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RouterConnectionError(f"[{self.name}] Gagal menghubungi {url}: {e}") from e

    def get_resource(self):
        """CPU load, free memory, uptime, versi RouterOS."""
        return self._get("system/resource")

    def get_interfaces(self):
        """Daftar interface beserta status running dan statistik trafik."""
        return self._get("interface")

    def get_logs(self, limit: int = 50):
        """Log sistem terbaru (limit entri paling akhir)."""
        logs = self._get("log")
        if isinstance(logs, list):
            return logs[-limit:]
        return []

    def get_dhcp_leases(self):
        """Daftar DHCP lease. Mengembalikan list kosong jika perangkat tidak
        menjalankan DHCP server (misalnya switch murni Layer 2)."""
        try:
            return self._get("ip/dhcp-server/lease")
        except RouterConnectionError:
            return []

    def get_firewall_counters(self):
        return self._get("ip/firewall/filter")

    def get_route_table(self):
        return self._get("ip/route")

    def get_vlan_interfaces(self):
        """Daftar interface VLAN yang benar-benar terdaftar di perangkat
        (name, vlan-id, parent interface) - lewat menu /interface/vlan."""
        return self._get("interface/vlan")

    def get_arp_table(self):
        """Tabel ARP (pasangan IP - MAC address per interface). Dipakai untuk
        menghitung jumlah client per VLAN tanpa bergantung pada DHCP server."""
        return self._get("ip/arp")

    def get_ip_addresses(self):
        """Daftar IP address yang di-assign ke masing-masing interface -
        dipakai untuk mendeteksi otomatis gateway/subnet tiap VLAN."""
        return self._get("ip/address")

    def monitor_traffic(self, interface: str) -> dict:
        """
        Mengambil pembacaan trafik INSTAN (rx/tx bits-per-second) memakai
        perintah RouterOS 'interface monitor-traffic' mode 'once' lewat REST API.
        Ini cara yang dianjurkan MikroTik untuk grafik realtime - lebih akurat
        dibanding menghitung delta dari counter kumulatif rx-byte/tx-byte yang
        tidak selalu tersedia di endpoint /rest/interface biasa.
        """
        url = f"{self.protocol}://{self.ip}/rest/interface/monitor-traffic"
        payload = {"interface": interface, "once": ""}
        try:
            resp = requests.post(
                url,
                json=payload,
                auth=self.auth,
                timeout=self.timeout + 3,
                verify=self.verify_ssl,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data[0] if data else {}
            return data
        except requests.exceptions.RequestException as e:
            raise RouterConnectionError(
                f"[{self.name}] Gagal membaca trafik interface '{interface}': {e}"
            ) from e
