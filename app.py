"""
app.py
Dashboard utama JaringKita (Streamlit).

Perubahan versi ini:
- VLAN dideteksi OTOMATIS dari router (vlan_registry.py), tidak ada hardcode.
  Label bisa dari comment MikroTik atau override manual lewat UI (opsional).
- Dashboard menampilkan status SELURUH interface (running/disabled) untuk
  router maupun switch.
- Grafik trafik ether1/trunk memakai 'interface monitor-traffic' (bukan lagi
  delta counter kumulatif yang sebelumnya sering kosong).
- Kontras kotak hasil AI diperbaiki (warna teks eksplisit, lihat ui_helpers.py).
- Menu VLAN Health sekarang punya dropdown pilih VLAN sumber & tujuan, plus
  info jumlah VLAN terdeteksi dan jumlah client per VLAN dari tabel ARP.

Jalankan dengan:
    streamlit run app.py
"""

import os
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu
from streamlit_autorefresh import st_autorefresh
from dotenv import load_dotenv

from collector import (
    router,
    switch,
    WAN_INTERFACE_NAME,
    TRUNK_INTERFACE_NAME,
    get_wan_trunk_traffic,
    get_running_interfaces,
    get_running_interfaces_with_traffic,
    get_interface_traffic_kbps,
    get_ip_address_table,
    get_dhcp_leases_grouped,
)
from device import RouterConnectionError
from vlan_registry import get_detected_vlans, get_vlan_client_counts_arp, save_manual_label
from active_test import ping_test_verbose, traceroute_test
from evidence import build_evidence, humanize_checks
from log_processor import classify_by_severity
from llm import simple_analysis
from ui_helpers import inject_right_sidebar_css, status_badge, render_ai_result
from report_export import render_download_buttons

load_dotenv()

MAX_POINTS = 30  # jumlah titik histori yang disimpan untuk grafik realtime

st.set_page_config(page_title="JaringKita - AI Network Assistant", layout="wide", page_icon="🧭")
inject_right_sidebar_css()

# ---------------------------------------------------------------------------
# Inisialisasi session_state
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "last_evidence": None,
    "history_resource": [],
    "history_wan_trunk": [],
    "history_vlan_wide": [],
    "history_switch": [],
    "last_diag": None,
    "current_logs": None,
    "current_log_groups": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ---------------------------------------------------------------------------
# Menu vertikal (ditampilkan di kanan lewat CSS di ui_helpers.py)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🧭 JaringKita")
    st.caption("AI Network Monitoring & Diagnostic Assistant")
    selected = option_menu(
        menu_title=None,
        options=[
            "Dashboard",
            "VLAN Health",
            "VLAN & Bandwidth",
            "Diagnostic Tools",
            "Switch Monitoring",
            "Log AI Analysis",
        ],
        icons=[
            "speedometer2",
            "shield-check",
            "bar-chart-line",
            "search",
            "hdd-network",
            "journal-text",
        ],
        default_index=0,
        styles={
            "container": {"padding": "0", "background-color": "transparent"},
            "icon": {"font-size": "16px"},
            "nav-link": {"font-size": "14px", "text-align": "left", "margin": "2px 0"},
            "nav-link-selected": {"background-color": "#4c8bf5"},
        },
    )
    st.divider()
    device_count = 1 + (1 if switch else 0)
    st.caption(f"📡 {device_count} perangkat dimonitor")
    st.caption(f"Router: `{router.ip}`")
    if switch:
        st.caption(f"Switch: `{switch.ip}`")
    else:
        st.caption("Switch: belum dikonfigurasi")


# ---------------------------------------------------------------------------
# Fungsi bantu tampilan
# ---------------------------------------------------------------------------
def _append_history(history_key: str, point: dict):
    st.session_state[history_key].append(point)
    st.session_state[history_key] = st.session_state[history_key][-MAX_POINTS:]


def _line_chart_from_history(history_key: str):
    hist = st.session_state[history_key]
    if hist:
        df = pd.DataFrame(hist).set_index("t")
        st.line_chart(df)
    else:
        st.info("Menunggu data pertama... (grafik akan muncul setelah refresh pertama)")


def _render_interface_status_table(interfaces: list[dict]):
    if not interfaces:
        st.info("Tidak ada data interface (perangkat mungkin tidak terhubung).")
        return
    rows = []
    has_traffic = any("rx_kbps" in i for i in interfaces)
    for iface in interfaces:
        if iface["disabled"]:
            status = "⚫ Disabled"
        elif iface["running"]:
            status = "🟢 Running (R)"
        else:
            status = "🔴 Down"
        row = {
            "Interface": iface["name"],
            "Tipe": iface["type"],
            "Status": status,
        }
        if has_traffic:
            rx = iface.get("rx_kbps")
            tx = iface.get("tx_kbps")
            row["Download (Kbps)"] = rx if rx is not None else "-"
            row["Upload (Kbps)"] = tx if tx is not None else "-"
        row["Keterangan"] = iface["comment"] or "-"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# =============================================================================
# HALAMAN: DASHBOARD
# =============================================================================
if selected == "Dashboard":
    st_autorefresh(interval=5000, key="refresh_dashboard")
    st.title("📊 Dashboard Monitoring Jaringan")
    st.caption("Diperbarui otomatis setiap 5 detik")

    col1, col2, col3 = st.columns(3)
    col1.metric("Perangkat Dimonitor", f"{device_count} unit")

    try:
        resource = router.get_resource()
        cpu = float(resource.get("cpu-load", 0) or 0)
        free_mem_mb = int(resource.get("free-memory", 0) or 0) / (1024 * 1024)

        col2.metric("CPU Router", f"{cpu:.0f}%")
        col3.metric("RAM Bebas Router", f"{free_mem_mb:.0f} MB")

        _append_history(
            "history_resource",
            {"t": datetime.now().strftime("%H:%M:%S"), "CPU (%)": cpu, "RAM Bebas (MB)": round(free_mem_mb, 1)},
        )
    except RouterConnectionError as e:
        st.error(f"Tidak bisa mengambil data resource router: {e}")

    st.subheader("Grafik CPU & RAM Router (Realtime)")
    _line_chart_from_history("history_resource")

    # --- Trafik WAN & Trunk ---
    st.subheader(f"Grafik Trafik: Internet ({WAN_INTERFACE_NAME}) & Trunk ke Switch ({TRUNK_INTERFACE_NAME})")
    traffic = get_wan_trunk_traffic()
    point = {"t": datetime.now().strftime("%H:%M:%S")}
    label_map = {"wan": f"Internet ({WAN_INTERFACE_NAME})", "trunk": f"Trunk ({TRUNK_INTERFACE_NAME})"}
    any_ok = False
    for key, data in traffic.items():
        point[f"{label_map.get(key, key)} Download (Kbps)"] = data["rx_kbps"]
        point[f"{label_map.get(key, key)} Upload (Kbps)"] = data["tx_kbps"]
        any_ok = any_ok or data["ok"]
    _append_history("history_wan_trunk", point)
    _line_chart_from_history("history_wan_trunk")

    if not any_ok:
        st.warning(
            f"Tidak bisa membaca trafik interface `{WAN_INTERFACE_NAME}`/`{TRUNK_INTERFACE_NAME}`. "
            "Kemungkinan nama interface di file .env tidak sesuai dengan yang ada di router. "
            "Cek nama interface yang benar lewat WinBox: `/interface print`, lalu sesuaikan "
            "`WAN_INTERFACE_NAME` dan `TRUNK_INTERFACE_NAME` di .env."
        )
    with st.expander("🔧 Debug: data mentah trafik (untuk troubleshooting)"):
        st.json(traffic)

    # --- Status interface router & switch (dengan trafik realtime per interface) ---
    st.subheader("Status Interface Router (Realtime)")
    st.caption("Trafik per interface diperbarui tiap refresh 5 detik - hanya interface aktif yang diukur trafiknya.")
    _render_interface_status_table(get_running_interfaces_with_traffic(router))

    if switch:
        st.subheader("Status Interface Switch (Realtime)")
        _render_interface_status_table(get_running_interfaces_with_traffic(switch))
    else:
        st.caption("Switch belum dikonfigurasi (isi SWITCH_IP di .env untuk mengaktifkan).")

    # --- Detail IP Address per interface (fisik maupun VLAN) ---
    st.subheader("🌐 Detail IP Address per Interface")
    ip_rows = get_ip_address_table(router)
    if ip_rows:
        df_ip = pd.DataFrame(ip_rows)
        df_ip["disabled"] = df_ip["disabled"].map({True: "⚫ Disabled", False: "🟢 Aktif"})
        df_ip = df_ip.rename(
            columns={
                "interface": "Interface",
                "address": "IP Address",
                "network": "Network",
                "disabled": "Status",
                "comment": "Keterangan",
            }
        )
        st.dataframe(df_ip, use_container_width=True, hide_index=True)
    else:
        st.info("Tidak ada data IP address yang bisa diambil dari router.")

    # --- Jumlah & daftar client per DHCP server pool ---
    st.subheader("📋 Client per DHCP Server Pool")
    dhcp_grouped = get_dhcp_leases_grouped(router)
    if dhcp_grouped:
        cols = st.columns(min(len(dhcp_grouped), 4))
        for col, (server, data) in zip(cols, dhcp_grouped.items()):
            col.metric(server, f"{data['count_active']} aktif", help=f"Total {data['total']} lease terdaftar")

        for server, data in dhcp_grouped.items():
            with st.expander(f"📦 Daftar client - pool '{server}' ({data['count_active']} aktif dari {data['total']} lease)"):
                st.dataframe(pd.DataFrame(data["leases"]), use_container_width=True, hide_index=True)
    else:
        st.info("Tidak ada data DHCP lease. Pastikan DHCP server sudah dikonfigurasi dan ada client yang terhubung.")

    # --- Ringkasan client per VLAN (berdasarkan ARP - saling melengkapi dengan DHCP di atas) ---
    st.subheader("Ringkasan Client per VLAN (Terdeteksi Otomatis, via ARP)")
    vlans = get_detected_vlans(router)
    if vlans:
        arp_counts = get_vlan_client_counts_arp(router)
        rows = [
            {"VLAN": f"{v['vlan_id']} - {v['label']}", "Jumlah Client": arp_counts.get(v["name"], 0)}
            for v in vlans
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Tidak ada VLAN terdeteksi di router. Lihat menu 'VLAN Health' untuk detail.")


# =============================================================================
# HALAMAN: VLAN HEALTH (deteksi VLAN otomatis + uji konektivitas dinamis)
# =============================================================================
elif selected == "VLAN Health":
    st.title("🛡️ Informasi VLAN & Uji Konektivitas")

    vlans = get_detected_vlans(router)
    arp_counts = get_vlan_client_counts_arp(router)

    st.metric("Jumlah VLAN Terdeteksi di Router", len(vlans))

    if vlans:
        table_rows = [
            {
                "VLAN ID": v["vlan_id"],
                "Nama Interface": v["name"],
                "Label": v["label"],
                "Gateway": v["gateway"] or "-",
                "Jumlah Client (ARP)": arp_counts.get(v["name"], 0),
            }
            for v in vlans
        ]
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        with st.expander("➕ Beri Label Kustom untuk VLAN (opsional)"):
            st.caption(
                "Kalau field 'comment' di MikroTik belum diisi, Anda bisa memberi label ramah "
                "di sini. Disimpan di file lokal `vlan_labels.json`, tidak mengubah konfigurasi router."
            )
            vlan_names = [v["name"] for v in vlans]
            label_lookup = {v["name"]: v["label"] for v in vlans}
            target_iface = st.selectbox(
                "Pilih VLAN", options=vlan_names, format_func=lambda n: f"{n} (saat ini: {label_lookup[n]})"
            )
            new_label = st.text_input("Label Baru", key="new_vlan_label")
            if st.button("💾 Simpan Label"):
                if new_label.strip():
                    save_manual_label(target_iface, new_label.strip())
                    st.success(f"Label untuk `{target_iface}` disimpan sebagai '{new_label.strip()}'.")
                    st.rerun()
                else:
                    st.warning("Isi dulu label barunya.")
    else:
        st.warning(
            "Tidak ada interface VLAN terdeteksi di router. Cek konfigurasi lewat WinBox: "
            "`/interface vlan print`. Pastikan ROUTER_IP/ROUTER_USER/ROUTER_PASS di .env sudah benar."
        )

    st.divider()
    st.subheader("Uji Konektivitas")

    if vlans:
        vlan_by_name = {v["name"]: v for v in vlans}
        options = list(vlan_by_name.keys())

        src_name = st.selectbox(
            "VLAN Sumber (label konteks pengujian)",
            options=options,
            format_func=lambda n: f"{vlan_by_name[n]['vlan_id']} - {vlan_by_name[n]['label']}",
            key="sel_src_vlan",
        )

        st.markdown("**Target Pengujian** — bebas, tidak harus VLAN yang terdeteksi")
        col_quick, col_ip = st.columns([1, 2])
        quick_options = ["-- Isi manual --"] + options
        quick_pick = col_quick.selectbox(
            "Pilihan cepat (opsional)",
            options=quick_options,
            format_func=lambda n: n
            if n == "-- Isi manual --"
            else f"Gateway VLAN {vlan_by_name[n]['vlan_id']} - {vlan_by_name[n]['label']}",
            key="sel_quick_target",
            help="Pilih VLAN untuk otomatis isi IP gateway-nya, atau biarkan 'Isi manual' dan ketik IP apa saja.",
        )
        default_ip = vlan_by_name[quick_pick]["gateway"] if quick_pick != "-- Isi manual --" else ""
        target_ip = col_ip.text_input(
            "IP / Host Tujuan",
            value=default_ip,
            placeholder="Contoh: 10.10.40.10, 8.8.8.8, google.com",
            key="target_ip_vlan_health",
        )

        protocol_choice = st.radio(
            "Metode Pengujian",
            options=["Ping (ICMP)", "TCP Port", "Ping + TCP Port"],
            index=2,
            horizontal=True,
            key="protocol_choice_vlan_health",
        )
        test_icmp = protocol_choice in ("Ping (ICMP)", "Ping + TCP Port")
        test_tcp = protocol_choice in ("TCP Port", "Ping + TCP Port")

        target_port = 443
        if test_tcp:
            target_port = st.number_input(
                "Port TCP yang diuji", min_value=1, max_value=65535, value=443, key="target_port_vlan_health"
            )

        st.caption(
            "⚠️ Pengujian dijalankan dari sudut pandang mesin yang menjalankan JaringKita saat ini, "
            "bukan simulasi virtual per-VLAN. Pastikan laptop benar-benar terhubung ke segmen VLAN "
            "sumber untuk hasil yang akurat (cek dengan `ipconfig`)."
        )

        if st.button("🔄 Jalankan Pengujian", key="btn_vlan_health"):
            if not target_ip:
                st.warning("Isi dulu IP/host tujuan.")
            elif not (test_icmp or test_tcp):
                st.warning("Pilih minimal satu metode pengujian.")
            else:
                dest_vlan_id = vlan_by_name[quick_pick]["vlan_id"] if quick_pick != "-- Isi manual --" else None
                with st.spinner("Menjalankan pengujian..."):
                    st.session_state.last_evidence = build_evidence(
                        vlan_by_name[src_name]["vlan_id"],
                        dest_vlan_id,
                        target_ip,
                        dest_port=int(target_port),
                        test_icmp=test_icmp,
                        test_tcp=test_tcp,
                    )

        evidence = st.session_state.last_evidence
        if evidence:
            st.markdown(f"### Status: {status_badge(evidence['status'])}")
            st.write("**Ringkasan Pengujian:**")
            for line in humanize_checks(evidence["checks"]):
                if "GAGAL" in line or "TIDAK dapat" in line:
                    icon = "❌"
                elif "berhasil" in line or "dapat diakses" in line:
                    icon = "✅"
                else:
                    icon = "ℹ️"
                st.write(f"{icon} {line}")

            if evidence["checks"].get("icmp_tested") and evidence["checks"].get("icmp_raw_output"):
                with st.expander("Lihat Detail Teknis Ping (ICMP) Mentah"):
                    st.code(evidence["checks"]["icmp_raw_output"], language="text")

            run_ai = st.button("🤖 Analisis dengan AI", key="btn_ai_vlan_health")
            if run_ai or evidence["anomaly_detected"]:
                try:
                    with st.spinner("AI sedang menganalisis..."):
                        result_text = simple_analysis(evidence)
                    st.write("")
                    render_ai_result(result_text)
                    st.write("")
                    render_download_buttons(
                        st,
                        report_title="Laporan Uji Konektivitas VLAN",
                        meta=evidence,
                        ai_text=result_text,
                        file_prefix="vlan_health",
                    )
                except Exception as e:
                    st.error(f"Gagal menghubungi Ollama: {e}")
            else:
                st.info("Tidak ada anomali terdeteksi - tekan tombol di atas untuk analisis manual.")
    else:
        st.info("Uji konektivitas belum tersedia karena tidak ada VLAN terdeteksi.")


# =============================================================================
# HALAMAN: VLAN & BANDWIDTH
# =============================================================================
elif selected == "VLAN & Bandwidth":
    st_autorefresh(interval=5000, key="refresh_vlan_bw")
    st.title("🧩 Statistik User & Bandwidth per VLAN")
    st.caption("Diperbarui otomatis setiap 5 detik · VLAN dideteksi otomatis dari router")

    vlans = get_detected_vlans(router)
    if not vlans:
        st.warning("Tidak ada VLAN terdeteksi di router. Lihat menu 'VLAN Health' untuk detail.")
    else:
        arp_counts = get_vlan_client_counts_arp(router)
        rows = []
        point = {"t": datetime.now().strftime("%H:%M:%S")}

        for v in vlans:
            traffic = get_interface_traffic_kbps(router, v["name"])
            rows.append(
                {
                    "VLAN": f"{v['vlan_id']} - {v['label']}",
                    "Jumlah User Aktif": arp_counts.get(v["name"], 0),
                    "Download (Kbps)": traffic["rx_kbps"],
                    "Upload (Kbps)": traffic["tx_kbps"],
                }
            )
            point[f"VLAN {v['label']}"] = traffic["rx_kbps"]

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        _append_history("history_vlan_wide", point)

        st.subheader("Grafik Konsumsi Bandwidth per VLAN")
        _line_chart_from_history("history_vlan_wide")
        st.caption(
            "Catatan performa: setiap VLAN dibaca satu per satu lewat monitor-traffic (~1 detik/VLAN). "
            "Kalau VLAN cukup banyak, refresh bisa terasa lebih lambat dari 5 detik - ini normal."
        )


# =============================================================================
# HALAMAN: DIAGNOSTIC TOOLS (ping/traceroute ke IP bebas + AI)
# =============================================================================
elif selected == "Diagnostic Tools":
    st.title("🔍 Analisis Ping, Traceroute & AI")
    st.write("Masukkan alamat IP tujuan, jalankan pengujian, lalu minta AI menjelaskan hasilnya.")

    target_ip = st.text_input("Alamat IP Tujuan", placeholder="Contoh: 10.10.40.10 atau 8.8.8.8")

    col_a, col_b = st.columns(2)
    run_ping = col_a.button("▶️ Jalankan Ping", use_container_width=True)
    run_trace = col_b.button("▶️ Jalankan Traceroute", use_container_width=True)

    if run_ping:
        if not target_ip:
            st.warning("Isi dulu alamat IP tujuan.")
        else:
            with st.spinner(f"Melakukan ping ke {target_ip}..."):
                result = ping_test_verbose(target_ip)
            st.session_state.last_diag = {
                "jenis_pengujian": "ping",
                "target": target_ip,
                "hasil_mentah": result["raw_output"],
                "berhasil": result["success"],
            }

    if run_trace:
        if not target_ip:
            st.warning("Isi dulu alamat IP tujuan.")
        else:
            with st.spinner(f"Melakukan traceroute ke {target_ip} (bisa memakan waktu)..."):
                raw = traceroute_test(target_ip)
            st.session_state.last_diag = {
                "jenis_pengujian": "traceroute",
                "target": target_ip,
                "hasil_mentah": raw,
                "berhasil": None,
            }

    diag = st.session_state.last_diag
    if diag:
        st.write(f"**Hasil {diag['jenis_pengujian'].capitalize()} ke `{diag['target']}`**")
        with st.expander("Lihat Detail Teknis (opsional)"):
            st.code(diag["hasil_mentah"], language="text")

        if st.button("🤖 Analisis Hasil dengan AI", key="btn_analyze_diag"):
            try:
                payload = dict(diag)
                payload["hasil_mentah"] = payload["hasil_mentah"][:2500]
                with st.spinner("AI sedang menganalisis..."):
                    result_text = simple_analysis(payload)
                render_ai_result(result_text)
                st.write("")
                render_download_buttons(
                    st,
                    report_title=f"Laporan {diag['jenis_pengujian'].capitalize()} ke {diag['target']}",
                    meta=payload,
                    ai_text=result_text,
                    file_prefix="diagnostic_tools",
                )
            except Exception as e:
                st.error(f"Gagal menghubungi Ollama: {e}")
    else:
        st.info("Masukkan IP dan jalankan salah satu pengujian di atas.")


# =============================================================================
# HALAMAN: SWITCH MONITORING
# =============================================================================
elif selected == "Switch Monitoring":
    st.title("🖧 Monitoring Switch (VLAN Distribution)")

    if switch is None:
        st.warning(
            "Switch belum dikonfigurasi. Isi `SWITCH_IP` (dan `SWITCH_USER`/`SWITCH_PASS` "
            "jika kredensialnya berbeda dari router) di file `.env`. Switch juga harus "
            "punya alamat IP management yang bisa diakses lewat REST API."
        )
    else:
        st_autorefresh(interval=5000, key="refresh_switch")
        st.caption("Diperbarui otomatis setiap 5 detik")

        try:
            resource = switch.get_resource()
            cpu = float(resource.get("cpu-load", 0) or 0)
            free_mem_mb = int(resource.get("free-memory", 0) or 0) / (1024 * 1024)

            col1, col2 = st.columns(2)
            col1.metric("CPU Switch", f"{cpu:.0f}%")
            col2.metric("RAM Bebas Switch", f"{free_mem_mb:.0f} MB")

            _append_history(
                "history_switch",
                {"t": datetime.now().strftime("%H:%M:%S"), "CPU (%)": cpu, "RAM Bebas (MB)": round(free_mem_mb, 1)},
            )

            st.subheader("Grafik CPU & RAM Switch (Realtime)")
            _line_chart_from_history("history_switch")

            st.subheader("Status Seluruh Port Switch")
            _render_interface_status_table(get_running_interfaces_with_traffic(switch))

        except RouterConnectionError as e:
            st.error(str(e))


# =============================================================================
# HALAMAN: LOG AI ANALYSIS
# =============================================================================
elif selected == "Log AI Analysis":
    st.title("📜 Log Jaringan & Analisis AI")

    source_options = ["Router"] + (["Switch"] if switch else [])
    source = st.radio("Sumber Log", source_options, horizontal=True)
    device_for_log = router if source == "Router" else switch

    if st.button("🔄 Ambil Log Terbaru"):
        try:
            logs = device_for_log.get_logs(limit=100)
            st.session_state.current_logs = logs
            st.session_state.current_log_groups = classify_by_severity(logs)
        except RouterConnectionError as e:
            st.error(str(e))

    groups = st.session_state.current_log_groups
    if groups:
        tab_err, tab_warn, tab_info = st.tabs(
            [
                f"🔴 Error ({len(groups['error'])})",
                f"🟡 Warning ({len(groups['warning'])})",
                f"⚪ Info ({len(groups['info'])})",
            ]
        )
        with tab_err:
            if groups["error"]:
                for entry in reversed(groups["error"]):
                    st.write(f"**{entry.get('time', '?')}** — {entry.get('message', '')}")
            else:
                st.caption("Tidak ada log error.")
        with tab_warn:
            if groups["warning"]:
                for entry in reversed(groups["warning"]):
                    st.write(f"**{entry.get('time', '?')}** — {entry.get('message', '')}")
            else:
                st.caption("Tidak ada log warning.")
        with tab_info:
            for entry in reversed(groups["info"][:30]):
                st.write(f"**{entry.get('time', '?')}** — {entry.get('message', '')}")

        st.divider()
        if st.button("🤖 Analisis & Rekomendasi AI", key="btn_analyze_logs"):
            summary_for_ai = {
                "sumber": source,
                "jumlah_error": len(groups["error"]),
                "jumlah_warning": len(groups["warning"]),
                "contoh_error": [e.get("message", "") for e in groups["error"][:5]],
                "contoh_warning": [e.get("message", "") for e in groups["warning"][:5]],
            }
            try:
                with st.spinner("AI sedang menganalisis log..."):
                    result_text = simple_analysis(summary_for_ai)
                st.subheader("Hasil Analisis & Rekomendasi AI")
                render_ai_result(result_text)
                st.write("")
                render_download_buttons(
                    st,
                    report_title=f"Laporan Analisis Log - {source}",
                    meta=summary_for_ai,
                    ai_text=result_text,
                    file_prefix="log_ai_analysis",
                )
            except Exception as e:
                st.error(f"Gagal menghubungi Ollama: {e}")
    else:
        st.info("Tekan tombol di atas untuk mengambil log terbaru.")
