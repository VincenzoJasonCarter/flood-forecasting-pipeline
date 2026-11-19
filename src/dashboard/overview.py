"""Isi ringkasan yang dipakai bersama dashboard dan PDF: banner status, angka utama kartu pos, kategori hujan.

Murni (tanpa Dash/ReportLab/BigQuery) supaya layar dan laporan unduhan selalu bercerita yang sama.
"""

import re

from .figures import SIAGA_NAME, river_label

# hujan harian BMKG (mm): ringan 5-20, sedang 20-50, lebat 50-100, sangat lebat 100-150, ekstrem >150;
# batas atas ruas terakhir hanya untuk menggambar skala
RAIN_NAMES = ("Ringan", "Sedang", "Lebat", "S. lebat", "Ekstrem")
RAIN_EDGES = (0, 20, 50, 100, 150, 200)


def num_id(value, decimals=1, sign=False):
    """Angka berformat Indonesia (koma desimal): 61,7 / +21,7."""
    return (f"{value:+.{decimals}f}" if sign else f"{value:.{decimals}f}").replace(".", ",")


def id_text(text):
    """Koma desimal di kalimat berangka ('160.0 cm' -> '160,0 cm'), sama dengan angka lain di layar dan PDF."""
    return re.sub(r"(\d)\.(\d)", r"\1,\2", text)


def rain_band(mm):
    """(kategori BMKG per hari, posisi penanda 0-100% pada skala lima ruas sama lebar)."""
    for i, name in enumerate(RAIN_NAMES):
        lo, hi = RAIN_EDGES[i], RAIN_EDGES[i + 1]
        if mm < hi or i == len(RAIN_NAMES) - 1:
            return name, round((i + min((mm - lo) / (hi - lo), 1.0)) / len(RAIN_NAMES) * 100, 1)


def worst_at(rows, horizon):
    """(status terparah, pos-pos yang berstatus itu) pada horizon; (None, []) kalau tak ada pos yang punya ambang."""
    graded = [r for r in rows if horizon in r["status_by_h"]]
    if not graded:
        return None, []
    level = min(r["status_by_h"][horizon] for r in graded)
    return level, [r for r in graded if r["status_by_h"][horizon] == level]


def worst_ahead(rows, horizons):
    """(status, horizon, pos-pos) terparah di seluruh horizon forecast; horizon terdekat menang kalau seri."""
    peak = None
    for h in horizons:
        level, at = worst_at(rows, h)
        if level is not None and (peak is None or level < peak[0]):
            peak = (level, h, at)
    return peak


def status_banner(rows, horizons, unit, finding):
    """Isi banner status (dashboard dan PDF): jenis (alert/safe/unknown), level, eyebrow, judul, teks, dan status
    terparah sekarang dan di tiap horizon.

    Peringatan kalau ada pos di atas Normal sekarang atau di prakiraan; aman kalau semuanya Normal;
    `finding` (kalimat temuan) jadi teks peringatan dan teks "belum bisa dinilai".
    """
    worst = []
    for h in [0] + list(horizons):
        level, _ = worst_at(rows, h)
        graded = [r for r in rows if h in r["status_by_h"]]
        worst.append({"label": "Sekarang" if h == 0 else f"+{h} {unit}", "level": level, "graded": len(graded),
                      "above": sum(r["status_by_h"][h] < 4 for r in graded)})
    out = {"worst": worst, "worst_title": f"Prakiraan Status Terburuk diantara {len(rows)} Pos" + (
        f" · {horizons[-1]} {unit} ke depan" if horizons else "")}
    peak = worst_ahead(rows, horizons)
    now_level, now_at = worst_at(rows, 0)
    levels = [lvl for lvl in (now_level, peak[0] if peak else None) if lvl is not None]
    if not horizons or not levels:
        return {**out, "kind": "unknown", "level": None, "eyebrow": "", "head": "Status belum bisa dinilai",
                "text": finding}
    level = min(levels)
    if level < 4:
        if peak and peak[0] < (now_level or 4):
            _, h, at = peak
            top = at[0]
            river = (river_label(top["station"]) or top["label"]).removeprefix("Kali ")
            eyebrow = f"PERINGATAN · SIAGA {peak[0]} DALAM {h} {unit.upper()}"
            head = f"{river} naik — {SIAGA_NAME[peak[0]]} diprakirakan dalam {h} {unit}"
        else:
            top = now_at[0]
            more = f" dan {len(now_at) - 1} pos lain" if len(now_at) > 1 else ""
            eyebrow = f"PERINGATAN · SIAGA {now_level} SEKARANG"
            head = f"{top['label']}{more} berstatus {SIAGA_NAME[now_level]}"
        return {**out, "kind": "alert", "level": level, "eyebrow": eyebrow, "head": head, "text": id_text(finding)}
    rising = [r["label"] for r in rows if r["rising"]]
    text = (f"{len(rows)} dari {len(rows)} pos TMA berstatus Normal dan diprakirakan tetap Normal "
            f"sampai {horizons[-1]} {unit} ke depan.")
    if rising:
        names = ", ".join(rising) if len(rising) <= 4 else ", ".join(rising[:3]) + ", dll."
        text += f" {len(rising)} pos diprakirakan naik dan perlu dipantau: {names}."
    return {**out, "kind": "safe", "level": 4, "eyebrow": "STATUS JAKARTA SAAT INI · SIAGA 4",
            "head": "Aman — semua pos Normal", "text": text}


def card_figure(a, unit, rise_cm, trend_steps):
    """(angka utama, keterangannya) kartu pos yang perlu perhatian.

    Selalu "puncak dalam +N jam" kalau ada prakiraan, dengan tambahan "menuju Siaga ..." dan/atau kenaikan terakhir;
    tanpa prakiraan: kenaikan terakhir, atau TMA sekarang."""
    r, now, worst = a["row"], a["now_level"], a["worst"]
    trend = (f"naik {num_id(a['trend'])} cm dalam {trend_steps} {unit} terakhir"
             if a["trend"] is not None and a["trend"] >= rise_cm else None)
    if r["peak"] is not None:
        parts = [f"puncak dalam +{r['peak_h']} {unit}"]
        if worst is not None and worst < (now or 4):
            parts.append(f"menuju {SIAGA_NAME[worst]} dalam {a['worst_h']} {unit}")
        if trend:
            parts.append(trend)
        return num_id(r["peak"]), " · ".join(parts)
    if trend:
        return num_id(a["trend"], sign=True), f"naik dalam {trend_steps} {unit} terakhir"
    return (num_id(r["now"]) if r["now"] is not None else "–"), "TMA sekarang"


def limit_line(a):
    """'Sudah 30 cm di atas Siaga 3 (80 cm)' atau '20 cm lagi ke Siaga 3 (200 cm)'; None tanpa ambang."""
    r, level = a["row"], a["now_level"]
    if r["now"] is None:
        return None
    if level is not None and level < 4 and level in r["limits"]:
        return f"Sudah {num_id(r['now'] - r['limits'][level])} cm di atas Siaga {level} ({r['limits'][level]:g} cm)"
    nxt = a["next"]
    return f"{num_id(nxt[2])} cm lagi ke Siaga {nxt[0]} ({nxt[1]:g} cm)" if nxt else None
