# JaringKita — Dashboard Monitoring MikroTik + AI Log Analysis

Dashboard Streamlit untuk memantau kesehatan router MikroTik, menguji konektivitas
antar-VLAN, dan menganalisis log router menggunakan LLM lokal (Ollama).

## Struktur Proyek

```
jaringkita/
├── app.py              # UI Streamlit utama (6 halaman menu vertikal di kanan)
├── device.py            # Kelas MikroTikDevice generik (dipakai untuk router & switch)
├── collector.py         # Instance router/switch + trafik realtime (monitor-traffic)
├── vlan_registry.py      # Deteksi OTOMATIS VLAN dari router + label manual opsional
├── active_test.py       # Ping (verbose), TCP test, traceroute
├── evidence.py          # Gabungkan data + evaluasi status + versi human-friendly
├── log_processor.py     # Ringkas & klasifikasi log (error/warning/info)
├── llm.py               # Panggil Ollama - output 1 paragraf STATUS/FAKTA/KESIMPULAN
├── ui_helpers.py         # CSS menu di kanan, badge status, kotak hasil AI (kontras aman)
├── requirements.txt     # Daftar dependency Python
├── .env.example         # Contoh konfigurasi - salin jadi .env
├── vlan_labels.json      # (dibuat otomatis) override label VLAN manual, opsional
└── README.md
```

## 0. Ringkasan Fitur (Versi Dikembangkan)

Dashboard sekarang punya 6 halaman, dipilih lewat **menu vertikal di sebelah kanan layar**:

| Halaman | Isi |
|---|---|
| **Dashboard** | Jumlah perangkat dimonitor, grafik CPU/RAM router realtime, grafik trafik `ether1` (internet) & trunk ke switch (via `monitor-traffic`), **status seluruh interface router & switch dengan trafik realtime per-interface (update 5 detik)**, **detail IP address per interface (fisik & VLAN)**, **jumlah & daftar client per DHCP server pool**, ringkasan client per VLAN (ARP) |
| **VLAN Health** | VLAN dideteksi otomatis dari router (bukan hardcode) + jumlah VLAN & client per VLAN dari tabel ARP + uji konektivitas dengan **target bebas (bukan cuma VLAN terdeteksi)** dan **pilihan protokol: Ping (ICMP) saja / TCP saja / keduanya** + analisis AI |
| **VLAN & Bandwidth** | Tabel jumlah user aktif (ARP) + grafik realtime konsumsi bandwidth tiap VLAN yang terdeteksi |
| **Diagnostic Tools** | Textbox untuk mengetik IP tujuan bebas → jalankan ping/traceroute → analisis AI (kontras warna sudah diperbaiki) |
| **Switch Monitoring** | CPU, RAM, dan status seluruh port switch dengan trafik realtime (perangkat kedua, terpisah dari router) |
| **Log AI Analysis** | Log asli router/switch dipisah 3 tab (Error/Warning/Info) + tombol Analisis & Rekomendasi AI |

**Format hasil AI** di semua halaman seragam: **satu paragraf** Bahasa Indonesia berisi
`STATUS: ... FAKTA: ... KESIMPULAN: ...` (KESIMPULAN sudah menggabungkan analisis penyebab
dan rekomendasi tindakan secara lugas).

### Uji Konektivitas Kini Fleksibel (VLAN Health)

Pengujian tidak lagi otomatis ping+TCP sekaligus ke gateway VLAN tujuan saja. Sekarang:

- **VLAN Sumber**: dropdown, hanya untuk label konteks pada evidence & analisis AI.
- **Target Pengujian**: bebas ketik IP/host apa saja (`10.10.40.10`, `8.8.8.8`, `google.com`,
  dst) — ada "pilihan cepat" opsional untuk auto-isi dari gateway VLAN yang terdeteksi.
- **Metode Pengujian**: pilih **Ping (ICMP) saja**, **TCP Port saja**, atau **keduanya**.
  Status HEALTHY/DEGRADED/DOWN dihitung hanya dari metode yang benar-benar dijalankan —
  tidak ada lagi asumsi "gateway reachable"/"route exists" yang dulu selalu `True` tanpa
  benar-benar diuji.

### Dua Cara Menghitung Jumlah Client (Saling Melengkapi)

- **Berdasarkan ARP** (`VLAN Health`, `VLAN & Bandwidth`, ringkasan di `Dashboard`): mencakup
  client IP statis maupun DHCP, dikelompokkan per interface VLAN.
- **Berdasarkan DHCP Lease** (`Dashboard` → "Client per DHCP Server Pool"): diambil langsung
  dari `/ip/dhcp-server/lease`, dikelompokkan per nama DHCP server/pool, lengkap dengan daftar
  IP/MAC/hostname/status tiap client — cocok kalau Anda ingin melihat siapa saja yang aktif,
  bukan cuma jumlahnya.

### Cara Kerja Deteksi VLAN Otomatis (Penting Dipahami)

`vlan_registry.py` mengambil daftar VLAN langsung dari router lewat `/interface/vlan` dan
`/ip/address` — **tidak ada VLAN yang ditulis manual di kode**. Label ramah-baca tiap VLAN
diambil berurutan dari:

1. **Override manual** yang Anda simpan lewat UI (menu VLAN Health → "Beri Label Kustom") — disimpan di `vlan_labels.json`, tidak mengubah konfigurasi router.
2. **Field `comment`** pada interface VLAN di MikroTik, kalau sudah diisi sysadmin (mis. `/interface vlan set vlan40-server comment="Server Sekolah"`).
3. **Nama interface VLAN itu sendiri**, sebagai fallback terakhir.

Gateway tiap VLAN juga terdeteksi otomatis dari `/ip/address` (IP yang di-assign ke interface
VLAN tsb) — dipakai sebagai target default saat menguji konektivitas, dan bisa diganti manual
ke IP host tertentu di menu VLAN Health.

**Trafik WAN/trunk** (`ether1`/`ether5`) tetap dikonfigurasi manual di `.env`
(`WAN_INTERFACE_NAME`, `TRUNK_INTERFACE_NAME`) karena itu interface fisik, bukan VLAN, dan
namanya tergantung pilihan desain topologi masing-masing sekolah.

## 1. Persiapan MikroTik

Pastikan REST API aktif di router (`/ip service` → `www` enabled, port default 80).
Buat user khusus untuk API (bukan admin utama) jika memungkinkan, dengan hak akses
`read` minimal untuk keperluan monitoring:

```
/user add name=ojm-api password=isi_password_kuat group=read
```

### 1.1 WAJIB untuk RouterOS < 7.9: Aktifkan HTTPS (www-ssl) untuk REST API

Cek versi RouterOS Anda dulu: `/system resource print` → lihat baris `version`.

**Kalau versi Anda di bawah 7.9** (misalnya 7.6, 7.7, 7.8): REST API di RouterOS versi
ini **hanya bisa diakses lewat HTTPS**, bukan HTTP biasa — ini bukan bug, memang begitu
desainnya (dukungan HTTP untuk REST API baru ditambahkan mulai RouterOS 7.9). Kalau Anda
mencoba `http://<ip-router>/rest/...` di versi ini, hasilnya akan selalu `404 Not Found`.

Aktifkan HTTPS dengan sertifikat self-signed (cukup untuk keperluan lab/kompetisi):

```
/certificate
add name=rest-cert common-name=OJMRouter days-valid=3650 key-usage=tls-server,digital-signature,key-cert-sign,crl-sign
sign rest-cert

/ip service
set www-ssl certificate=rest-cert disabled=no
```

Verifikasi dengan curl (flag `-k` supaya menerima sertifikat self-signed, sama seperti
`VERIFY_SSL=false` yang dipakai kode Python):

```powershell
curl.exe -i -k -u "admin:password_anda" https://192.168.99.1/rest/system/resource
```

Kalau responnya `200 OK` dengan data JSON (bukan lagi `404`), berarti sudah benar dan
dashboard JaringKita (yang sudah memakai HTTPS secara default) akan bisa terhubung.

**Alternatif:** upgrade RouterOS ke 7.9 atau lebih baru (`/system package update`), yang
mengaktifkan dukungan HTTP biasa untuk REST API sehingga tidak perlu setup sertifikat.
Tapi mengingat waktu mendekati deadline, opsi HTTPS di atas lebih aman karena tidak
mengubah firmware router yang sedang dipakai untuk kompetisi.

## 2. Persiapan Ollama

```bash
# Install Ollama terlebih dahulu (lihat https://ollama.com)
ollama pull qwen3.5:4b
ollama list   # pastikan qwen3.5:4b muncul
```

## 3. Setup Python

```bash
cd jaringkita
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

## 4. Konfigurasi Environment

```bash
cp .env.example .env
```

Lalu edit `.env` dan isi:
- `ROUTER_IP` — IP router MikroTik Anda
- `ROUTER_USER` / `ROUTER_PASS` — kredensial API (sebaiknya user khusus, bukan admin utama)
- `DEMO_DEST_IP` — IP target untuk demo VLAN Health (misalnya IP di VLAN Server)

**PENTING:** jangan pernah menampilkan isi file `.env` di layar saat syuting/screen-recording,
dan jangan commit file `.env` ke Git manapun (hanya `.env.example` yang boleh dibagikan).

## 5. Menjalankan Dashboard

```bash
streamlit run app.py
```

Buka browser ke `http://localhost:8501`.

## 6. Urutan Testing yang Disarankan (Sebelum Syuting)

1. Cek koneksi dasar ke router:
   ```powershell
   python -c "from collector import router; print(router.get_resource())"
   ```
2. **Cek endpoint monitor-traffic** (ini yang dipakai untuk grafik trafik ether1/trunk/VLAN,
   endpoint yang sebelumnya sempat kosong) — ganti `ether1` sesuai nama interface Anda:
   ```powershell
   python -c "from collector import router; print(router.monitor_traffic('ether1'))"
   ```
   Kalau hasilnya dict berisi `rx-bits-per-second`/`tx-bits-per-second`, endpoint bekerja.
   Kalau error atau field itu tidak ada, laporkan hasilnya — kemungkinan versi RouterOS Anda
   memakai nama field yang sedikit berbeda dan `collector.py` perlu disesuaikan.
3. Cek deteksi VLAN otomatis:
   ```powershell
   python -c "from collector import router; from vlan_registry import get_detected_vlans; import json; print(json.dumps(get_detected_vlans(router), indent=2))"
   ```
   Pastikan semua VLAN yang ada di router muncul di sini sebelum lanjut ke dashboard.
4. Jalankan `ollama run qwen3.5:4b` sekali secara manual dulu untuk memastikan model
   sudah ter-load dan responsif (percobaan pertama biasanya paling lambat).
5. Buka dashboard (`streamlit run app.py`), cek tiap halaman satu per satu sesuai urutan
   di menu, dari Dashboard sampai Log AI Analysis.
6. Simulasikan skenario gangguan (lihat dokumen storyboard) dan pastikan status berubah
   dari HEALTHY ke DEGRADED/DOWN secara konsisten sebelum direkam.

## 7. Panduan Khusus: Windows 11 + VS Code

Langkah ini menggantikan bagian 3-5 di atas jika Anda mengerjakan di Windows 11 dengan VS Code.

### 7.1 Install Python

1. Download Python 3.11+ dari https://python.org (bukan dari Microsoft Store, supaya
   PATH lebih mudah dikontrol).
2. Saat instalasi, **centang "Add python.exe to PATH"** — ini sering terlewat dan
   menyebabkan `python` tidak dikenali di terminal.
3. Cek di terminal: `python --version`

### 7.2 Buka Proyek di VS Code

1. Ekstrak `jaringkita.zip`.
2. Buka VS Code → `File > Open Folder` → pilih folder `jaringkita`.
3. Install extension **Python** (by Microsoft) dari tab Extensions (Ctrl+Shift+X)
   kalau belum ada — ini memberi syntax highlighting, IntelliSense, dan pemilihan
   interpreter.

### 7.3 Buat & Aktifkan Virtual Environment

Buka terminal terintegrasi di VS Code (`` Ctrl+` ``). Secara default terminalnya PowerShell.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Masalah umum:** kalau muncul error seperti *"running scripts is disabled on this system"*,
itu karena PowerShell execution policy. Jalankan sekali ini (tidak perlu admin, cukup untuk user Anda):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Lalu ulangi `.venv\Scripts\Activate.ps1`. Alternatif lebih simpel: ganti terminal ke
**Command Prompt** (klik dropdown panah di pojok kanan panel terminal VS Code → pilih
"Command Prompt"), lalu aktivasi dengan:

```cmd
.venv\Scripts\activate.bat
```

### 7.4 Pilih Interpreter yang Benar di VS Code

Setelah venv aktif, pastikan VS Code memakainya juga (bukan Python sistem):

1. `Ctrl+Shift+P` → ketik "Python: Select Interpreter"
2. Pilih yang path-nya mengandung `.venv\Scripts\python.exe`

Ini penting supaya fitur seperti "Go to Definition" dan linting VS Code membaca
package yang sama dengan yang dipakai saat `streamlit run`.

### 7.5 Install Dependency

```powershell
pip install -r requirements.txt
```

### 7.6 Setup .env

```powershell
Copy-Item .env.example .env
```

Buka `.env` di VS Code, isi `ROUTER_IP`, `ROUTER_USER`, `ROUTER_PASS` sesuai router Anda.
**Tutup tab file `.env` sebelum mulai screen-record/syuting** supaya tidak tidak sengaja
terlihat di recording.

### 7.7 Install & Jalankan Ollama

1. Download installer dari https://ollama.com (ada versi Windows native, tidak perlu WSL).
2. Setelah install, buka terminal baru (boleh di luar VS Code) lalu:
   ```powershell
   ollama pull qwen3.5:4b
   ollama list
   ```
3. Ollama berjalan sebagai service di background secara otomatis setelah install —
   tidak perlu dijalankan manual tiap kali, tapi kalau ragu bisa cek dengan:
   ```powershell
   curl http://localhost:11434/api/tags
   ```

### 7.8 Jalankan Dashboard

Di terminal VS Code (pastikan `.venv` masih aktif, prompt akan menunjukkan `(.venv)` di depan):

```powershell
streamlit run app.py
```

Browser akan terbuka otomatis ke `http://localhost:8501`. Kalau tidak, buka manual di alamat itu.

### 7.9 Windows Defender Firewall

Saat pertama kali menjalankan `streamlit run` atau Ollama, Windows biasanya menampilkan
popup "Windows Defender Firewall has blocked some features". Klik **Allow access**
(pilih "Private networks" cukup, tidak perlu "Public") supaya dashboard bisa diakses
dan bisa menghubungi router di jaringan lokal.

### 7.10 Catatan Penting soal Koneksi Fisik ke VLAN

Script pengujian (`active_test.py`) melakukan ping/TCP test **dari sudut pandang laptop
Windows Anda saat itu** — bukan dari VLAN tertentu secara virtual. Artinya:

- Kalau Anda ingin mendemonstrasikan pengujian "dari VLAN Siswa", laptop Windows harus
  benar-benar terhubung secara fisik (kabel LAN atau WiFi yang di-bridge) ke access port
  VLAN Siswa saat skrip dijalankan, dan mendapat IP di range `10.10.30.0/24`.
- Cek IP aktif laptop dengan `ipconfig` di terminal sebelum menjalankan tombol pengujian,
  supaya yakin laptop memang berada di segmen yang benar saat demo direkam.
- Kalau laptop yang sama dipakai untuk semua tab (VLAN Health, Router Monitoring, Log AI),
  pastikan laptop tetap punya jalur ke `ROUTER_IP` untuk REST API terlepas dari VLAN mana
  dia sedang terhubung (biasanya ini berarti REST API management sebaiknya dari VLAN Admin
  atau jaringan manajemen terpisah, sementara pengujian ping/TCP dari VLAN yang sedang diuji).

## Batasan yang Perlu Disadari (dan sebaiknya disebutkan di video)

- REST API di setup ini menggunakan HTTP, bukan HTTPS — cukup untuk lab pengembangan,
  tapi untuk produksi sebaiknya diaktifkan HTTPS dengan sertifikat valid.
- Dashboard ini memakai refresh manual (tombol), bukan real-time otomatis, untuk
  menjaga kesederhanaan dan stabilitas saat demo.
- AI tidak pernah mengubah konfigurasi router secara langsung — semua rekomendasi
  memerlukan verifikasi dan tindakan manual oleh manusia.
