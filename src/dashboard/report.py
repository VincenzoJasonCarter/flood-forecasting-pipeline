"""Laporan unduhan: dari angka di dashboard ke temuan, alasan dan tindakan per pos, sebagai PDF A4.

Penilaian dan isi murni (tanpa Dash/BigQuery) supaya bisa diuji: app.py memanggil `build_report` dengan
snapshot yang sama dengan yang sedang ditampilkan; `report_content` menyusun isinya dan dashboard/pdf.py
menggambarnya. Ambang dan teks tindakan dari `laporan:` di config/dashboard.yaml.
"""

import math

import pandas as pd

from .figures import BULAN, SIAGA_NAME, hilir_kecamatan, rain_totals, station_rain
from .overview import num_id, status_banner
from .pdf import render
from .report_sections import build as build_sections

STALE_STEPS = 2  # data lebih tua dari sekian langkah dianggap basi


def wave_speed_kmh(tempuh, ruas_km):
    """Kecepatan rambat gelombang (km/jam): jarak sungai ruas kalibrasi (hilir.json `ruas_km`) / lag puncaknya
    (`laporan.tempuh` di config); None kalau salah satunya tidak ada."""
    if not tempuh:
        return None
    up, down = tempuh["ruas"]
    km = (ruas_km.get(up) or {}).get(down)
    return km / tempuh["lag_jam"] if km else None


def _event_step(row, now_level, worst, worst_h):
    """Langkah dari as_of saat kondisi terparah pos terjadi: sekarang kalau status sekarang yang terparah, jam
    pertama status terparah prakiraan, atau jam puncak prakiraan kalau pos tetap Normal tapi naik."""
    if now_level is not None and now_level < 4 and (worst is None or now_level <= worst):
        return 0
    if worst is not None and worst < 4:
        return worst_h
    return row["peak_h"] if row["rising"] and row["peak_h"] is not None else 0


def downstream_times(info, kmh, severest, event_at, as_of, tenggat):
    """Satu baris per kecamatan hilir, terdekat dulu: kelurahannya, jarak, waktu tempuh, jam tiba dan tenggat.

    `info` = entri hilir.json pos; `event_at` = jam kondisi terparah di pos (None: tanpa jam, misalnya
    granularity harian). Jam tiba = event_at + waktu tempuh, dibulatkan ke bawah ke jam penuh (lebih awal =
    lebih aman). Tenggat = jam tiba - `tenggat[severest].jam`, "segera" kalau sudah lewat as_of. [] tanpa jarak
    atau kecepatan.
    """
    km_by_kec = (info or {}).get("kecamatan_km") or {}
    if not kmh or not km_by_kec:
        return []
    kelurahan = hilir_kecamatan(None, {None: info})
    kota = {kec: k for _, kec, k in info.get("kelurahan", [])}
    lead = (tenggat or {}).get(severest)
    out = []
    for kec, km in km_by_kec.items():
        if km is None:
            continue
        hours = km / kmh
        arrive = event_at + pd.Timedelta(hours=math.floor(hours)) if event_at is not None else None
        due = None
        if arrive is not None and lead:
            at = arrive - pd.Timedelta(hours=lead["jam"])
            due = {"tindakan": lead["tindakan"], "at": at, "now": at <= as_of}
        out.append({"kecamatan": kec, "kelurahan": kelurahan.get(kec, []), "kota": kota.get(kec), "km": km, "jam": hours,
                    "tiba": arrive, "tenggat": due})
    return sorted(out, key=lambda x: x["km"])


def trend_cm(levels, station, steps):
    """Perubahan TMA (cm) dalam `steps` langkah terakhir; None kalau datanya kurang dari dua titik."""
    if station not in levels.columns:
        return None
    window = levels[station].iloc[-(steps + 1):].dropna()
    return round(float(window.iloc[-1] - window.iloc[0]), 1) if len(window) >= 2 else None


def next_limit(row):
    """(status, batas cm, sisa cm) batas siaga berikutnya di atas TMA sekarang; None kalau sudah Awas atau tanpa ambang."""
    level = row["status_by_h"].get(0)
    for nxt in range(level - 1, 0, -1) if level else ():
        if nxt in row["limits"]:
            limit = row["limits"][nxt]
            return nxt, limit, round(limit - row["now"], 1)
    return None


def _alarming(row):
    return row["rising"] or min(row["status_by_h"].values(), default=4) < 4


def upstream(rows):
    """{pos: [pos hulu di aliran yang sama yang naik atau keluar dari Normal]}; urutan rows = hulu ke hilir."""
    out, seen = {}, {}
    for r in rows:
        if r["aliran"] is None:
            continue
        prior = seen.setdefault(r["aliran"], [])
        out[r["station"]] = [u for u in prior if _alarming(u)]
        prior.append(r)
    return out


def _worst_ahead(row, horizons):
    """(status, horizon) terparah di horizon forecast, horizon terdekat kalau seri; (None, None) tanpa status."""
    graded = [(row["status_by_h"][h], h) for h in horizons if h in row["status_by_h"]]
    return min(graded) if graded else (None, None)


def _upstream_note(row, horizons, unit):
    level, h = _worst_ahead(row, horizons)
    if level is not None and level < 4:
        return f"{row['label']} Siaga {level} pada +{h} {unit}"
    if row["status_by_h"].get(0, 4) < 4:
        return f"{row['label']} Siaga {row['status_by_h'][0]} sekarang"
    return f"{row['label']} {row['change']:+.1f} cm"


def assess(rows, snap, horizons, cfg):
    """Satu penilaian per pos: status sekarang dan terparah ke depan, sinyal (alasan) dan tindakan yang disarankan.

    `cfg` = isi `laporan:` di config ditambah unit, rise_cm, rain_steps dan (opsional) hilir dari hilir.json.
    Pos masuk "perlu perhatian" kalau punya minimal satu alasan; urutan = paling parah dulu, lalu yang naik
    paling banyak. `hilir` = {kecamatan: [kelurahan]} di bantaran hilir pos, {} kalau tidak ada datanya.
    """
    unit, rise_cm = cfg["unit"], cfg["rise_cm"]
    cells = (snap["model"] or {}).get("rain_cells") or {}
    ups = upstream(rows)
    as_of = snapshot_as_of(snap)
    tenggat = (cfg.get("tempuh") or {}).get("tenggat")
    out = []
    for r in rows:
        now_level = r["status_by_h"].get(0)
        worst, worst_h = _worst_ahead(r, horizons)
        trend = trend_cm(snap["levels"], r["station"], cfg["trend_steps"])
        rain = station_rain(snap["rain"], cells.get(r["station"]))
        rain_mm = round(float(rain.tail(cfg["rain_steps"]).sum()), 1) if rain is not None else None
        nxt = next_limit(r)

        reasons = []
        if worst is not None and worst < (now_level or 4):  # tanpa TMA sekarang: prakiraan di atas Normal
            since = (f"dari {r['now']:.1f} cm sekarang" if now_level is not None
                     else "TMA sekarang tidak terbaca")
            reasons.append(f"Diprakirakan naik ke Siaga {worst} ({SIAGA_NAME[worst]}) pada +{worst_h} {unit}: "
                           f"{r['forecasts'][worst_h]:.1f} cm, {since}.")
        elif worst is not None and now_level is not None and now_level < 4:
            end = r["status_by_h"].get(horizons[-1])
            reasons.append(f"Siaga {now_level} sekarang, diprakirakan turun ke Siaga {end} pada +{horizons[-1]} {unit}."
                           if end is not None and end > now_level else
                           f"Siaga {now_level} sekarang dan diprakirakan bertahan sampai +{horizons[-1]} {unit}.")
        if r["rising"]:
            reasons.append(f"Puncak prakiraan {r['peak']:.1f} cm pada +{r['peak_h']} {unit}, "
                           f"{r['change']:+.1f} cm dari sekarang.")
        if trend is not None and trend >= rise_cm:
            reasons.append(f"Sudah naik {trend:.1f} cm dalam {cfg['trend_steps']} {unit} terakhir.")
        if nxt and nxt[2] <= cfg["near_limit_cm"] and not (worst is not None and worst <= nxt[0]):
            reasons.append(f"Tinggal {nxt[2]:.1f} cm lagi ke batas Siaga {nxt[0]} ({nxt[1]:g} cm).")
        if rain_mm is not None and rain_mm >= cfg["heavy_rain_mm"]:
            reasons.append(f"Hujan 24 jam terakhir di sel model {rain_mm:.1f} mm (lebat).")
        if ups.get(r["station"]):
            reasons.append(f"Pos hulu di aliran {r['aliran']} sedang naik: "
                           f"{', '.join(_upstream_note(u, horizons, unit) for u in ups[r['station']])}.")

        severest = min([s for s in (now_level, worst) if s is not None], default=None)
        action = cfg["tindakan"][severest] if severest is not None and severest < 4 else cfg["tindakan"]["pantau"]
        step = _event_step(r, now_level, worst, worst_h)
        event_at = as_of + pd.Timedelta(hours=step) if unit == "jam" and as_of is not None else None
        out.append({"row": r, "now_level": now_level, "worst": worst, "worst_h": worst_h, "trend": trend,
                    "rain_mm": rain_mm, "next": nxt, "reasons": reasons, "action": action if reasons else None,
                    "hilir": hilir_kecamatan(r["station"], cfg.get("hilir", {})), "event_step": step,
                    "event_at": event_at,
                    "tempuh": downstream_times(cfg.get("hilir", {}).get(r["station"]), cfg.get("kmh"), severest,
                                               event_at, as_of, tenggat)})
    return out


def _priority(a):
    r = a["row"]
    return min(r["status_by_h"].values(), default=5), -(r["change"] if r["change"] is not None else float("-inf"))


def attention(assessments):
    """Pos yang punya minimal satu alasan, paling parah dulu, lalu yang naik paling banyak."""
    return sorted((a for a in assessments if a["reasons"]), key=_priority)


def snapshot_as_of(snap):
    """Waktu data terakhir: as_of forecast, atau TMA terakhir kalau belum ada forecast; None kalau keduanya kosong."""
    forecast, levels = snap["forecast"], snap["levels"]
    if not forecast.empty:
        return forecast["as_of"].max()
    return levels.index.max() if len(levels) else None


def stale_note(now, as_of, unit):
    """Peringatan data basi (lebih tua dari STALE_STEPS langkah), atau None."""
    step = pd.Timedelta(1, "h" if unit == "jam" else "D")
    if as_of is None or now - as_of <= STALE_STEPS * step:
        return None
    return (f"Data terakhir {_age(now - as_of, unit)} lalu: prakiraan mungkin sudah tidak mewakili kondisi "
            "sekarang. Cek job pipeline sebelum memakai laporan ini.")


def selection_note(info):
    """'median MAE 1.23 saat seleksi' dari info model; None kalau statistiknya tidak tersimpan."""
    metric = info.get("selection_metric")
    if not metric or info.get("stat_value") is None:
        return None
    return f"{info['stat']} {str(metric).upper()} {info['stat_value']:.2f} saat seleksi"


def _stamp(ts):
    return f"{ts.day} {BULAN[ts.month - 1]} {ts.year} {ts:%H:%M}"


def _age(delta, unit):
    hours = max(delta.total_seconds() / 3600, 0)
    return f"{hours:.0f} jam" if unit == "jam" or hours < 48 else f"{hours / 24:.0f} hari"


def _model_line(snap):
    info = snap["model"] or {}
    if info.get("best_model"):
        note = selection_note(info)
        return str(info["best_model"]).upper() + (f" ({note})" if note else "")
    forecast = snap["forecast"]
    return ", ".join(sorted(forecast["model"].unique())).upper() if not forecast.empty else "–"


def tempuh_basis(cfg, rows):
    """'10,6 km/jam (Katulampa -> Depok: 42,4 km dalam ~4 jam)' dari config dan jarak ruas kalibrasi."""
    up, down = cfg["tempuh"]["ruas"]
    label = {r["station"]: r["label"] for r in rows}
    km = cfg["kmh"] * cfg["tempuh"]["lag_jam"]
    return (f"{num_id(cfg['kmh'])} km/jam ({label.get(up, up)} → {label.get(down, down)}: {num_id(km)} km "
            f"dalam ~{cfg['tempuh']['lag_jam']:g} jam)")


def _notes(snap, rows, now, as_of, cfg, assessments):
    """Hal yang membatasi kepercayaan pada laporan ini; yang paling penting (data basi) dulu."""
    unit, notes = cfg["unit"], []
    stale = stale_note(now, as_of, unit)
    if stale:
        notes.append(stale)
    missing = [r["label"] for r in rows if not r["forecasts"]]
    if missing:
        notes.append(f"Tanpa prakiraan: {', '.join(missing)}. Pos ini hanya dinilai dari TMA dan hujan.")
    unlimited = [r["label"] for r in rows if not r["limits"]]
    if unlimited:
        notes.append(f"Tanpa batas siaga: {', '.join(unlimited)}. Status siaga pos ini tidak dinilai.")
    if snap["rain"] is None:
        notes.append("Data hujan tidak terbaca; sinyal hujan tidak dinilai.")
    notes.append("Batas siaga dari tabel Status Siaga Pintu Air, Pedoman Pengendalian Banjir BPBD DKI Jakarta (2020).")
    if cfg.get("hilir"):
        notes.append("Wilayah hilir = perkiraan: kelurahan di dekat alur sungai pos menurut OpenStreetMap, bukan "
                     "daftar resmi BPBD. Wilayah yang benar-benar tergenang bergantung pada debit, hujan lokal dan "
                     "pintu air.")
    if cfg.get("kmh") and any(a["tempuh"] for a in assessments):
        notes.append(f"Waktu tempuh = perkiraan: jarak sepanjang sungai di OpenStreetMap dibagi kecepatan rambat "
                     f"{tempuh_basis(cfg, rows)}. Kecepatan itu dari ruas hulu yang curam; di ruas kota yang landai "
                     "gelombang cenderung lebih lambat, jadi jam tiba cenderung lebih awal dari kenyataan. Selisih "
                     "antarkejadian sekitar 1 jam. Belum divalidasi dengan TMA pintu air hilir.")
    notes.append(f"Model prakiraan: {_model_line(snap)}. Prakiraan punya galat; perlakukan angka per pos sebagai "
                 "perkiraan, bukan kepastian.")
    notes.append("Tindakan diringkas dari Pedoman Pengendalian Banjir BPBD DKI Jakarta (2020). Keputusan operasional "
                 "tetap mengikuti arahan BPBD DKI Jakarta.")
    return notes


def report_content(snap, rows, horizons, now, finding, cfg, sources=""):
    """Isi laporan sebagai dict untuk pdf.render: kepala, temuan, pos yang perlu perhatian, semua pos, catatan."""
    unit = cfg["unit"]
    assessments = assess(rows, snap, horizons, cfg)
    needed = attention(assessments)
    as_of = snapshot_as_of(snap)

    bullets = [f"{len(needed)} dari {len(rows)} pos perlu perhatian." if needed else
               "Tidak ada pos yang perlu tindakan khusus; lanjutkan pemantauan rutin."]
    totals = rain_totals(snap["rain"], cfg["rain_steps"])
    if len(totals):
        bullets.append(f"Hujan 24 jam di DAS rata-rata {totals.mean():.1f} mm di {len(totals)} sel grid, "
                       f"terderas {totals.max():.1f} mm.")
    falling = [a["row"]["label"] for a in assessments if a["trend"] is not None and a["trend"] <= -cfg["rise_cm"]]
    if falling:
        bullets.append(f"Surut dalam {cfg['trend_steps']} {unit} terakhir: {', '.join(falling)}.")

    graded = [r for r in rows if 0 in r["status_by_h"]]
    info = snap["model"] or {}
    kpis = {"levels": [r["status_by_h"][0] for r in graded], "normal": sum(r["status_by_h"][0] == 4 for r in graded),
            "off": [f"{r['label']} {SIAGA_NAME[r['status_by_h'][0]]}" for r in graded if r["status_by_h"][0] < 4],
            "rain_mean": float(totals.mean()) if len(totals) else None,
            "rain_max": float(totals.max()) if len(totals) else None, "rain_cells": len(totals),
            "metric": str(info.get("selection_metric") or "").upper(), "stat": info.get("stat", "median"),
            "stat_value": info.get("stat_value"),
            "model": str(info["best_model"]).upper() if info.get("best_model") else _model_line(snap)}
    meta = [f"Data per {_stamp(as_of)} WIB" if as_of is not None else "Data belum ada",
            f"dibuat {_stamp(now)} WIB"]
    if horizons:
        meta.append(f"prakiraan sampai +{horizons[-1]} {unit}")
    if cfg.get("demo"):  # dashboard.demo: data palsu, ditandai di judul dan keterangan
        meta.insert(0, cfg["demo"].upper())
    return {
        "title": "Laporan Pantauan dan Prakiraan Banjir DKI Jakarta" + (" (DEMO)" if cfg.get("demo") else ""),
        "pantau": cfg["tindakan"]["pantau"],
        "cover": {"number": f"LPB-{(as_of if as_of is not None else now):%Y%m%d-%H%M}",
                  "kepada": (cfg.get("sampul") or {}).get("kepada"),
                  "disusun_oleh": (cfg.get("sampul") or {}).get("disusun_oleh"),
                  "data": f"{_stamp(as_of)} WIB" if as_of is not None else "Data belum ada",
                  "made": f"{_stamp(now)} WIB", "demo": cfg.get("demo"),
                  "gaya": (cfg.get("sampul") or {}).get("gaya", "formal")}, "stamp": _stamp(as_of if as_of is not None else now), "meta": meta,
        "severest": min((s for r in rows for s in r["status_by_h"].values()), default=None),
        "span": f"sampai +{horizons[-1]} {unit}" if horizons else "sekarang",
        "attention_title": "Perlu tindakan" if any(min(a["row"]["status_by_h"].values(), default=4) < 4
                                                   for a in needed) else "Perlu dipantau",
        "falling": falling, "banner": status_banner(rows, horizons, unit, finding), "kpis": kpis, "rise_cm": cfg["rise_cm"],
        "finding": finding, "bullets": bullets, "attention": needed, "assessments": assessments,
        "horizons": list(horizons), "unit": unit, "trend_steps": cfg["trend_steps"],
        "notes": _notes(snap, rows, now, as_of, cfg, assessments), "sources": sources,
        "tempuh_basis": tempuh_basis(cfg, rows) if cfg.get("kmh") else None, "as_of": as_of,
        "tenggat": (cfg.get("tempuh") or {}).get("tenggat") or {},
        **build_sections(assessments, needed, snap, horizons, cfg, as_of),
    }


def build_report(snap, rows, horizons, now, finding, cfg, sources=""):
    """PDF A4 (bytes) yang bisa dibuka, dicetak, atau dikirim apa adanya."""
    return render(report_content(snap, rows, horizons, now, finding, cfg, sources))
