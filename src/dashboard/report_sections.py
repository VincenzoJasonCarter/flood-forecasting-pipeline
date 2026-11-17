"""Isi laporan berbentuk naskah untuk Pemprov: ringkasan, satu bagian per sungai, pos lain yang dipantau.

Murni (tanpa ReportLab/Dash/BigQuery) supaya kalimatnya bisa diuji. report.report_content memanggil `build`
dengan penilaian per pos (report.assess); dashboard/pdf.py menggambar kalimat, grafik dan tabelnya.

Satu bagian = satu sungai (hilir.json `sungai`) yang punya pos di atas Normal sekarang atau di prakiraan. Semua
pos di sungai itu ikut (grafik TMA bertumpuk, hulu ke hilir); waktu tiba ke kecamatan dari tiap pos yang punya
waktu tempuh, satu lajur per pos, karena pos hulu dan hilir memberi perkiraan yang berbeda.
"""

import pandas as pd

from .figures import BULAN, SIAGA_NAME, river_label, station_rain
from .overview import id_text, num_id, rain_band

CHART_STEPS = {"jam": 36, "hari": 14}  # panjang TMA terukur di grafik


def status_phrase(level):
    """'Siaga 1 (Awas)', 'Siaga 2', 'Siaga 3 (Waspada)', 'Normal'; 'tanpa status' kalau None."""
    if level is None:
        return "tanpa status"
    if level == 4:
        return "Normal"
    return f"Siaga {level}" + ("" if SIAGA_NAME[level] == "Siaga" else f" ({SIAGA_NAME[level]})")


def status_short(level):
    """'Awas, Siaga 1' / 'Siaga 2' / 'Waspada, Siaga 3' / 'Normal', untuk di dalam kurung."""
    if level is None or level == 4:
        return status_phrase(level)
    return f"Siaga {level}" if SIAGA_NAME[level] == "Siaga" else f"{SIAGA_NAME[level]}, Siaga {level}"


def clock(ts, as_of):
    """'21:00', atau '01:00 (18 Nov)' kalau bukan tanggal yang sama dengan data."""
    text = f"{ts:%H:%M}"
    if as_of is not None and ts.normalize() != as_of.normalize():
        text += f" ({ts.day} {BULAN[ts.month - 1]})"
    return text


def join(items):
    """'A', 'A dan B', 'A, B, dan C'."""
    items = list(items)
    if len(items) <= 2:
        return " dan ".join(items)
    return ", ".join(items[:-1]) + ", dan " + items[-1]


def _cm(value):
    return f"{num_id(value)} cm"


def _severest(a):
    levels = [s for s in (a["now_level"], a["worst"]) if s is not None]
    return min(levels) if levels else None


def _river(a, hilir):
    return (hilir.get(a["row"]["station"]) or {}).get("sungai") or a["row"]["label"]


def _when(h, unit, as_of):
    """'+3 jam (00:00 (18 Nov))' -> '+3 jam, pukul 00:00 (18 Nov)'; tanpa jam untuk granularity harian."""
    if unit == "jam" and as_of is not None:
        return f"+{h} jam, pukul {clock(as_of + pd.Timedelta(hours=h), as_of)}"
    return f"+{h} {unit}"


def station_text(a, horizons, unit, as_of, trend_steps, rise_cm):
    """Satu paragraf kondisi pos: status dan TMA sekarang, tren, prakiraan puncak dan status, hujan, pos hulu."""
    r, now, worst = a["row"], a["now_level"], a["worst"]
    at = f" pada pukul {clock(as_of, as_of)} WIB" if unit == "jam" and as_of is not None else ""
    if r["now"] is None:
        parts = [f"TMA Pos {r['label']} tidak terbaca{at}."]
    else:
        text = f"Pos {r['label']} berstatus {status_phrase(now)} dengan TMA {_cm(r['now'])}{at}"
        if now is not None and now < 4 and now in r["limits"]:
            text += f", {_cm(r['now'] - r['limits'][now])} di atas batas Siaga {now} ({r['limits'][now]:g} cm)"
        elif a["next"]:
            text += f", {_cm(a['next'][2])} di bawah batas Siaga {a['next'][0]} ({a['next'][1]:g} cm)"
        parts = [text + "."]
    trend = a["trend"]
    if trend is not None and abs(trend) >= rise_cm:
        parts.append(f"TMA {'naik' if trend > 0 else 'turun'} {_cm(abs(trend))} dalam {trend_steps} {unit} terakhir.")
    elif trend is not None:
        parts.append(f"TMA relatif stabil dalam {trend_steps} {unit} terakhir.")
    if r["forecasts"]:
        if r["peak"] is not None and (r["now"] is None or r["peak"] > r["now"]):
            parts.append(f"Model memprakirakan puncak {_cm(r['peak'])} pada {_when(r['peak_h'], unit, as_of)}.")
        end = r["status_by_h"].get(horizons[-1]) if horizons else None
        if worst is not None and worst < (now or 4):
            parts.append(f"Status diprakirakan naik ke {status_phrase(worst)} pada {_when(a['worst_h'], unit, as_of)}.")
        elif end is not None and now is not None and end > now:
            parts.append(f"Status diprakirakan turun ke {status_phrase(end)} pada +{horizons[-1]} {unit} "
                         f"({_cm(r['forecasts'][horizons[-1]])}).")
        elif end is not None:
            parts.append(f"Status diprakirakan bertahan {status_phrase(end)} sampai +{horizons[-1]} {unit}.")
    else:
        parts.append("Prakiraan untuk pos ini tidak tersedia.")
    if a["rain_mm"] is not None:
        parts.append(f"Hujan 24 jam terakhir di sel model pos ini {num_id(a['rain_mm'])} mm "
                     f"({rain_band(a['rain_mm'])[0].lower().replace('s. ', 'sangat ')}).")
    parts += [id_text(x) for x in a["reasons"] if x.startswith("Pos hulu")]
    return " ".join(parts)


def _chart(a, snap, cells, horizons, unit, as_of):
    """Data grafik satu pos: TMA terukur (CHART_STEPS terakhir), prakiraan, hujan per langkah, batas siaga."""
    r, station = a["row"], a["row"]["station"]
    step = pd.Timedelta(1, "h" if unit == "jam" else "D")
    levels = snap["levels"]
    actual = levels[station].dropna().tail(CHART_STEPS[unit]) if station in levels.columns else pd.Series(dtype=float)
    rain = station_rain(snap["rain"], cells.get(station))
    if rain is not None and len(actual):
        rain = rain.loc[actual.index.min() - step:]
        rain = rain.resample("D").sum() if unit == "hari" else rain
    forecast = [(as_of + h * step, r["forecasts"][h]) for h in horizons if h in r["forecasts"]] if as_of is not None else []
    return {"station": station, "label": r["label"], "level": a["now_level"], "worst": _severest(a),
            "actual": list(actual.items()), "forecast": forecast, "limits": r["limits"],
            "rain": list(rain.items()) if rain is not None else [], "as_of": as_of, "unit": unit}


def arrivals(group, as_of):
    """Linimasa tiba per kecamatan: lajur = pos yang punya waktu tempuh, baris = kecamatan (yang paling cepat
    terkena dulu). None kalau tak satu pun pos di sungai ini punya waktu tempuh."""
    lanes = [a for a in group if a["tempuh"] and (_severest(a) or 4) < 4] or [a for a in group if a["tempuh"]]
    if not lanes:  # tanpa jarak/kecepatan: daftar kecamatan dan kelurahan hilir saja, tanpa jam
        listed = next((a for a in sorted(group, key=lambda x: _severest(x) or 5) if a["hilir"]), None)
        if listed is None:
            return None
        return {"lanes": [], "as_of": as_of, "rows": [{"kecamatan": kec, "kelurahan": kel, "kota": None, "marks": {}}
                                                      for kec, kel in listed["hilir"].items()],
                "source": listed["row"]["label"]}
    rows = {}
    for a in lanes:
        for t in a["tempuh"]:
            row = rows.setdefault(t["kecamatan"], {"kecamatan": t["kecamatan"], "kelurahan": t["kelurahan"],
                                                   "kota": t.get("kota"), "marks": {}})
            row["marks"][a["row"]["station"]] = t
    def first(row):  # noqa: E306
        marks = row["marks"].values()
        times = [m["tiba"] for m in marks if m["tiba"] is not None]
        return (min(times) if times else pd.Timestamp.max, min(m["km"] for m in marks))
    return {"lanes": [{"station": a["row"]["station"], "label": a["row"]["label"], "level": _severest(a)}
                      for a in lanes],
            "rows": sorted(rows.values(), key=first), "as_of": as_of}


def impact_text(title, group, arr, kmh, as_of):
    """Paragraf wilayah terdampak: jumlah kecamatan dan kelurahan, kotanya, dan kapan gelombang tiba."""
    if not arr:
        return None
    kel = {k for row in arr["rows"] for k in row["kelurahan"]}
    kota = sorted({row["kota"] for row in arr["rows"] if row.get("kota")})
    names = join(lane["label"] for lane in arr["lanes"]) or arr.get("source", "")
    text = (f"Menurut alur {title} di OpenStreetMap, bantaran hilir Pos {names} melewati {len(arr['rows'])} "
            f"kecamatan dan {len(kel)} kelurahan" + (f" di {join(kota)}" if kota else "") + ".")
    for lane in arr["lanes"]:
        marks = [(row["kecamatan"], row["marks"][lane["station"]]) for row in arr["rows"]
                 if lane["station"] in row["marks"]]
        timed = sorted((m["tiba"], kec) for kec, m in marks if m["tiba"] is not None)
        if not timed:
            continue
        first, last = timed[0], timed[-1]
        speed = f"Dengan kecepatan rambat sekitar {num_id(kmh)} km/jam, g" if lane is arr["lanes"][0] and kmh else "G"
        text += (f" {speed}elombang {status_phrase(lane['level']) if lane['level'] else ''} dari Pos {lane['label']} "
                 f"diperkirakan tiba di Kecamatan {first[1]} sekitar pukul {clock(first[0], as_of)}")
        text += (f" dan di Kecamatan {last[1]} sekitar pukul {clock(last[0], as_of)}." if last is not first else ".")
    return text.replace("  ", " ")


def action_items(group, arr, tindakan, as_of):
    """Rekomendasi bernomor: per pos yang menentukan tindakan, teks SOP lalu tenggat per kecamatan."""
    items = []
    for a in sorted(group, key=lambda x: _severest(x) or 5):
        level = _severest(a)
        if level is None or level == 4:
            continue
        base = f"{tindakan[level]}"
        rows = [(row["kecamatan"], row["marks"].get(a["row"]["station"])) for row in (arr or {}).get("rows", [])]
        due = [(m["tenggat"], kec) for kec, m in rows if m and m["tenggat"]]
        head = f"Pos {a['row']['label']} {status_phrase(level)}: {base}"
        if due:
            soon = [kec for d, kec in due if d["now"]]
            later = {}
            for d, kec in due:
                if not d["now"]:
                    later.setdefault(d["at"], []).append(kec)
            parts = ([f"segera di {join(soon)}"] if soon else []) + [
                f"paling lambat pukul {clock(at, as_of)} di {join(kecs)}" for at, kecs in sorted(later.items())]
            head += f" Tenggat {due[0][0]['tindakan']}: " + "; ".join(parts) + "."
        elif rows:
            head += f" Kecamatan hilir: {join(kec for kec, m in rows if m)}."
        items.append(head)
    return items


def build(assessments, needed, snap, horizons, cfg, as_of):
    """{"sections": [bagian per sungai], "watch": [pos lain yang dipantau], "summary": [paragraf ringkasan]}."""
    unit, hilir = cfg["unit"], cfg.get("hilir", {})
    cells = (snap["model"] or {}).get("rain_cells") or {}
    flagged = {a["row"]["station"] for a in needed}
    by_river = {}
    for a in assessments:
        by_river.setdefault(_river(a, hilir), []).append(a)
    sections, covered = [], set()
    for river, group in by_river.items():
        if not any((_severest(a) or 4) < 4 for a in group):
            continue
        title = river_label(group[0]["row"]["station"]) or river
        arr = arrivals(group, as_of)
        sections.append({
            "river": river, "title": title, "level": min(_severest(a) or 5 for a in group),
            "stations": [{"label": a["row"]["label"], "level": a["now_level"], "worst": _severest(a),
                          "text": station_text(a, horizons, unit, as_of, cfg["trend_steps"], cfg["rise_cm"]),
                          "chart": _chart(a, snap, cells, horizons, unit, as_of)} for a in group],
            "impact": impact_text(title, group, arr, cfg.get("kmh"), as_of), "arrivals": arr,
            "actions": action_items(group, arr, cfg["tindakan"], as_of),
        })
        covered |= {a["row"]["station"] for a in group}
    sections.sort(key=lambda s: s["level"])
    watch = [{"label": a["row"]["label"], "level": a["now_level"],
              "text": " ".join(id_text(x) for x in a["reasons"])} for a in needed if a["row"]["station"] not in covered]
    return {"sections": sections, "watch": watch, "headline": headline(sections),
            "summary": summary(assessments, sections, watch, snap, horizons, cfg, as_of, flagged)}


def headline(sections):
    """Angka utama sampul dan ringkasan: kecamatan, kelurahan dan kota terdampak, gelombang paling cepat per sungai
    (sungai terparah dulu), dan tindakan paling mendesak (yang "segera" dulu, lalu tenggat paling awal)."""
    rows = [row for s in sections if s["arrivals"] for row in s["arrivals"]["rows"]]
    firsts = []
    for s in sections:
        timed = sorted((m["tiba"], row["kecamatan"]) for row in (s["arrivals"] or {}).get("rows", [])
                       for m in row["marks"].values() if m["tiba"] is not None)
        if timed:
            firsts.append({"river": s["title"], "kecamatan": timed[0][1], "tiba": timed[0][0]})
    dues = sorted(((m["tenggat"]["at"], m["tenggat"]["now"], m["tenggat"]["tindakan"], row["kecamatan"])
                   for row in rows for m in row["marks"].values() if m["tenggat"]), key=lambda x: (not x[1], x[0]))
    urgent = None
    if dues:
        at, now, what, kec = dues[0]
        urgent = {"tindakan": what, "kecamatan": kec, "at": at, "now": now}
    return {"kecamatan": len({row["kecamatan"] for row in rows}),
            "kelurahan": len({k for row in rows for k in row["kelurahan"]}),
            "kota": sorted({row["kota"] for row in rows if row.get("kota")}), "rivers": [s["title"] for s in sections],
            "firsts": firsts, "urgent": urgent}


def urgent_text(urgent, as_of):
    """'persiapan di Kecamatan Jagakarsa, paling lambat pukul 23:00' / '..., segera'."""
    when = "segera" if urgent["now"] else f"paling lambat pukul {clock(urgent['at'], as_of)}"
    return f"{urgent['tindakan']} di Kecamatan {urgent['kecamatan']}, {when}"


def summary(assessments, sections, watch, snap, horizons, cfg, as_of, flagged):
    """Paragraf ringkasan: kondisi sekarang, prakiraan, wilayah terdampak, hujan, tindakan paling mendesak."""
    unit, out = cfg["unit"], []
    graded = [a for a in assessments if a["now_level"] is not None]
    off = [a for a in graded if a["now_level"] < 4]
    stamp = f"pukul {clock(as_of, as_of)} WIB" if as_of is not None else "saat ini"
    text = (f"Pada {as_of.day} {BULAN[as_of.month - 1]} {as_of.year} {stamp}, " if as_of is not None else "Saat ini, ")
    if off:
        text += (f"{len(off)} dari {len(graded)} pos pantau tinggi muka air (TMA) berada di atas status Normal: "
                 + join(f"{a['row']['label']} ({status_short(a['now_level'])})" for a in sorted(off, key=lambda x: x["now_level"]))
                 + ".")
    else:
        text += f"seluruh {len(graded)} pos pantau TMA berstatus Normal."
    rising = [a for a in assessments if a["worst"] is not None and a["worst"] < (a["now_level"] or 4)]
    if rising and horizons:
        text += (f" Dalam {horizons[-1]} {unit} ke depan, model memprakirakan "
                 + join(f"Pos {a['row']['label']} naik ke {status_phrase(a['worst'])} pada {_when(a['worst_h'], unit, as_of)}"
                        for a in sorted(rising, key=lambda x: (x["worst"], x["worst_h"]))) + ".")
    elif horizons:
        text += f" Tidak ada pos yang diprakirakan naik status dalam {horizons[-1]} {unit} ke depan."
    out.append(text)

    head = headline(sections)
    if head["kecamatan"]:
        text = (f"Wilayah yang berpotensi terdampak berada di bantaran {join(head['rivers'])}: {head['kecamatan']} "
                f"kecamatan dan {head['kelurahan']} kelurahan" + (f" di {join(head['kota'])}" if head["kota"] else "")
                + ".")
        if head["firsts"]:
            text += " Gelombang paling cepat tiba di " + "; ".join(
                f"{f['river']} mulai Kecamatan {f['kecamatan']} sekitar pukul {clock(f['tiba'], as_of)}"
                for f in head["firsts"]) + "."
        out.append(text)

    rain = [a["rain_mm"] for a in assessments if a["rain_mm"] is not None]
    if rain:
        top = max(assessments, key=lambda a: a["rain_mm"] if a["rain_mm"] is not None else -1)
        out.append(f"Hujan 24 jam terakhir terbesar tercatat di sel model Pos {top['row']['label']}, "
                   f"{num_id(top['rain_mm'])} mm ({rain_band(top['rain_mm'])[0].lower().replace('s. ', 'sangat ')}).")

    if head["urgent"]:
        out.append(f"Tindakan paling mendesak: {urgent_text(head['urgent'], as_of)}. Rincian per sungai ada di bagian "
                   "berikut; status semua pos ada di Lampiran A.")
    elif sections or watch:
        out.append("Belum ada tenggat persiapan atau evakuasi; lanjutkan pemantauan. Rincian per sungai ada di bagian "
                   "berikut; status semua pos ada di Lampiran A.")
    return out
