"""
log_processor.py
Meringkas dan mengklasifikasi log MikroTik sebelum ditampilkan di UI atau
dikirim ke LLM.
"""

from collections import Counter

SEVERITY_TOPICS = {"error", "critical", "warning"}


def summarize_logs(logs: list[dict]) -> dict:
    """Ringkasan jumlah kemunculan tiap topic + daftar entri yang mengandung
    topic 'penting' (error/critical/warning)."""
    topic_counter = Counter()
    flagged = []

    for entry in logs:
        topics_str = entry.get("topics", "")
        topic_list = [t.strip() for t in topics_str.split(",") if t.strip()]

        for t in topic_list:
            topic_counter[t] += 1

        if any(sev in topic_list for sev in SEVERITY_TOPICS):
            flagged.append(entry)

    return {
        "log_summary_counts": dict(topic_counter),
        "flagged_entries": flagged[:10],
        "total_logs_checked": len(logs),
    }


def classify_by_severity(logs: list[dict]) -> dict:
    """
    Mengelompokkan log ke 3 kategori berdasarkan topics: error, warning, info.
    Dipakai untuk menampilkan log dalam 3 tab terpisah di UI (bukan satu tabel
    campur aduk).
    """
    groups = {"error": [], "warning": [], "info": []}
    for entry in logs:
        topics = [t.strip() for t in entry.get("topics", "").split(",") if t.strip()]
        if any(t in ("error", "critical") for t in topics):
            groups["error"].append(entry)
        elif "warning" in topics:
            groups["warning"].append(entry)
        else:
            groups["info"].append(entry)
    return groups
