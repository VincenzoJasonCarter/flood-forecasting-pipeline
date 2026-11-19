"""Dash app, dua halaman (hasil `make predict-bq`):

/      ringkasan: peta pos + ringkasan, grafik TMA satu pos (rentang 3 hari s.d. 1 tahun), laporan singkat
/pos   detail: papan status siaga per aliran, lalu pos terpilih (?nama=): peta hilir, batas dan prakiraan
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from .data import (GRANULARITY, REFRESH_SECONDS, REPORT, RISE_THRESHOLD_CM, STATIONS, STEP_HOURS, UNIT, load_history,
                   load_snapshot)
from .figures import (BULAN, HILIR, HILIR_BUFFER_M, HILIR_RUAS_KM, SIAGA_NAME, blank_figure, gauge, hilir_kecamatan,
                      map_figure, rain_totals, river_label, station_figure, station_rows)
from .overview import RAIN_NAMES, card_figure, num_id, rain_band, status_banner, worst_at, worst_ahead
from .report import (assess, attention, build_report, next_limit, selection_note, snapshot_as_of, stale_note,
                     wave_speed_kmh)

logger = logging.getLogger(__name__)

FONTS = "https://fonts.googleapis.com/css2?family=Geist:wght@400;500;700&display=swap"

# suppress_callback_exceptions: tiap halaman hanya memuat komponennya sendiri, callback halaman lain menunggu
app = Dash(__name__, title="Flood Forecast", external_stylesheets=[FONTS], suppress_callback_exceptions=True)
server = app.server  # untuk gunicorn kalau nanti di-deploy

DETAIL_PATH = "/pos"
# filter rentang grafik di halaman detail: kunci -> (label, jam). Yang muat di snapshot (history_steps)
# diambil dari sana, yang lebih panjang dibaca per pos lewat load_history
RANGES = {"3d": ("3 hari", 72), "1w": ("1 minggu", 7 * 24), "1m": ("1 bulan", 30 * 24), "1y": ("1 tahun", 365 * 24)}

NO_FORECAST = "Belum ada forecast di forecast_output. Jalankan make predict-bq."
NO_LIMITS = "Ambang siaga belum diisi di config/dashboard.yaml."
NO_BQ = "Gagal membaca BigQuery, lihat log server."
WIB = timezone(timedelta(hours=7))  # jam data API dan "diperbarui" memakai waktu Jakarta
RAIN_STEPS = 24  # "hujan 24 jam": tabel hujan selalu per jam, juga saat granularity TMA harian
REPORT_CFG = {**REPORT, "unit": UNIT, "rise_cm": RISE_THRESHOLD_CM, "rain_steps": RAIN_STEPS, "hilir": HILIR,
              "kmh": wave_speed_kmh(REPORT.get("tempuh"), HILIR_RUAS_KM)}
DEMO = None  # teks penanda data palsu di header (dashboard.demo, `make dashboard-demo`); None = data nyata
ATTN_CARDS = 3  # kartu "perlu tindakan" di ringkasan; sisanya hanya disebut namanya
SOURCES = ("TMA dan status siaga: sisteminformasibanjir.jakarta.go.id · Batas siaga dan tindakan: Pedoman "
           "Pengendalian Banjir BPBD DKI Jakarta (2020) · Hujan: Open-Meteo, ECMWF IFS · Batas wilayah dan "
           "sungai: © OpenStreetMap contributors (ODbL) · "
           "Koordinat pos dan wilayah hilir perkiraan")


def _snapshot(force=False):
    """Snapshot dict, atau None kalau BigQuery gagal; error dicatat di log."""
    try:
        return load_snapshot(force=force)
    except Exception:
        logger.exception("Gagal membaca BigQuery")
        return None


def _rows(snap):
    return station_rows(snap["levels"], snap["forecast"], STATIONS, RISE_THRESHOLD_CM)


def _horizons(snap):
    forecast = snap["forecast"]
    return sorted(int(h) for h in forecast["horizon"].unique()) if not forecast.empty else []


def _date_id(ts):
    return f"{ts.day} {BULAN[ts.month - 1]} {ts.year}"


def _ago(delta):
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} mnt lalu"
    if minutes < 48 * 60:
        return f"{minutes // 60} jam lalu"
    return f"{minutes // (24 * 60)} hari lalu"


def _dot(level):
    return html.I(className=f"dot s{level or 0}")


def _status_text(level):
    return SIAGA_NAME[4] if level == 4 else f"Siaga {level}"


def _finding(rows, horizons):
    """Kalimat pertama yang dibaca: pos terparah, sekarang atau di prakiraan, kapan, dan setinggi apa.

    Status sekarang ikut dinilai: pos yang sedang Siaga tetapi diprakirakan surut tidak boleh
    membuat kalimat ini berbunyi "semua Normal".
    """
    if not horizons:
        return NO_FORECAST
    peak = worst_ahead(rows, horizons)
    now_level, now_at = worst_at(rows, 0)
    if peak is None and now_level is None:
        return NO_LIMITS
    ahead = peak[0] if peak else 4
    if ahead == 4 and now_level in (None, 4):
        if peak is None:  # yang punya ambang tidak punya prakiraan
            return NO_LIMITS
        return f"Semua {len(rows)} pos Normal sekarang dan diprakirakan tetap Normal sampai +{horizons[-1]} {UNIT}."
    if now_level is not None and now_level < ahead:  # sekarang lebih parah dari prakiraan mana pun
        top = now_at[0]
        end = top["status_by_h"].get(horizons[-1])
        text = f"{top['station']} {_status_text(now_level)} ({SIAGA_NAME[now_level]}) sekarang: {top['now']:.1f} cm"
        text += (f", diprakirakan turun ke {_status_text(end)} pada +{horizons[-1]} {UNIT}."
                 if end is not None and end > now_level else ".")
    else:
        level, h, at = peak
        top = at[0]
        start = f"{top['now']:.1f} → " if top["now"] is not None else ""
        unread = "" if top["now"] is not None else ", TMA sekarang tidak terbaca"
        text = (f"{top['station']} diprakirakan Siaga {level} ({SIAGA_NAME[level]}) pada +{h} {UNIT}: "
                f"{start}{top['forecasts'][h]:.1f} cm{unread}.")
    others = [r for r in rows if r is not top and min(r["status_by_h"].values(), default=4) < 4]
    if others:
        text += f" Juga di atas Normal: {', '.join(r['label'] for r in others)}."
    return text


def _default_station(rows):
    """Pos paling parah di seluruh horizon, lalu yang naik paling banyak."""
    if not rows:
        return None
    return min(rows, key=lambda r: (min(r["status_by_h"].values(), default=5),
                                    -(r["change"] if r["change"] is not None else float("-inf"))))["station"]


_id = num_id


def _river(station):
    return river_label(station)


def _severity(row):
    return min(row["status_by_h"].values(), default=5)


def _data_stamp(snap, now):
    """Pil di bilah atas: titik kesegaran (hijau, kuning kalau data basi), waktu data, dan kapan dibaca."""
    as_of = snapshot_as_of(snap)
    read = html.Span(f"Dicek {datetime.now(WIB):%H:%M}", className="stamp-sub")
    if as_of is None:
        return [html.I(className="live stale"), html.Span("Belum ada data"), read]
    stale = stale_note(now, as_of, UNIT) is not None
    when = f"{as_of:%H:%M} WIB" if GRANULARITY == "hourly" else _date_id(as_of)
    return [html.I(className="live stale" if stale else "live"),
            html.Span(f"Data {when} · {_ago(now - as_of)}"), read]


def _banner_worst(banner):
    """Kolom kanan banner: status terparah (dan jumlah pos di atas Normal) sekarang dan di tiap horizon."""
    cols = [html.Div([
        html.Span(w["label"], className="bw-label"),
        html.Span(className=f"bw-bar s{w['level'] or 0}"),
        html.Span(SIAGA_NAME[w["level"]] if w["level"] else "–", className=f"bw-status s{w['level'] or 0}"),
        html.Span(f"{w['above']} pos di atas Normal" if w["above"] else f"{w['graded']}/{w['graded']} pos Normal",
                  className="bw-sub"),
    ], className="bw-col") for w in banner["worst"]]
    return html.Div([html.Div(banner["worst_title"], className="bw-title"),
                     html.Div(cols, className="bw-cols", style={"--cols": len(cols)})], className="bw")


def _banner(snap, rows, horizons):
    """(className, isi) banner: peringatan menurut status terparah sekarang/prakiraan, aman kalau semuanya Normal.

    Satu tempat yang menjawab "apakah ada yang perlu dilakukan": warna, ikon dan judul mengikuti data.
    Isinya dari report.status_banner, sama dengan banner di PDF.
    """
    b = status_banner(rows, horizons, UNIT, _finding(rows, horizons))
    if b["kind"] == "unknown":
        return "banner", [html.Div([html.Span("!", className="bn-icon neutral"),
                                    html.Div([html.H1(b["head"]), html.P(b["text"])], className="bn-text")],
                                   className="bn-main")]
    level = b["level"]
    icon = html.Span("✓" if b["kind"] == "safe" else "!", className=f"bn-icon s{level}")
    text = html.Div([html.Div(b["eyebrow"], className=f"bn-eyebrow s{level}"), html.H1(b["head"]), html.P(b["text"])],
                    className="bn-text")
    return f"banner {'safe' if b['kind'] == 'safe' else f'alert s{level}'}", [
        html.Div([icon, text], className="bn-main"), _banner_worst(b)]


def _kpi_cards(snap, rows):
    """Tiga kartu di bawah banner: pos Normal sekarang, hujan 24 jam di DAS, keandalan model (NSE)."""
    graded = [r for r in rows if 0 in r["status_by_h"]]
    normal = sum(r["status_by_h"][0] == 4 for r in graded)
    off = [r for r in graded if r["status_by_h"][0] < 4]
    sub = (", ".join(f"{r['label']} {SIAGA_NAME[r['status_by_h'][0]]}" for r in off) if 0 < len(off) <= 2
           else f"{len(off)} pos di atas Normal" if off else "Tidak ada pos Waspada, Siaga, atau Awas")
    pos = html.Div([
        html.Span("Pos berstatus Normal · sekarang", className="kc-label"),
        html.Div([html.Span(f"{normal}/{len(graded)}", className="kc-num"), html.Span("pos", className="unit")],
                 className="kc-value"),
        html.Div([html.Span(className=f"seg-bar s{r['status_by_h'][0]}") for r in graded], className="seg-bars"),
        html.Div(sub, className="kc-sub"),
    ], className="card kpi-card")

    totals = rain_totals(snap["rain"], RAIN_STEPS)
    if len(totals):
        mean = float(totals.mean())
        name, at = rain_band(mean)
        rain = html.Div([
            html.Span("Hujan 24 jam di DAS", className="kc-label"),
            html.Div([html.Span(_id(mean), className="kc-num"), html.Span("mm", className="unit"),
                      html.Span(name, className="chip")], className="kc-value"),
            html.Div([html.Span(className=f"rain-seg r{i}") for i in range(len(RAIN_NAMES))]
                     + [html.Span(className="rain-mark", style={"left": f"{at}%"})], className="rain-bar"),
            html.Div([html.Span(n) for n in RAIN_NAMES], className="rain-names"),
            html.Div(f"Rata-rata {len(totals)} sel grid · terderas {_id(float(totals.max()))} mm", className="kc-sub"),
            html.Div("Lebih kecil, lebih baik", className="kc-hint"),
        ], className="card kpi-card")
    else:
        rain = html.Div([html.Span("Hujan 24 jam di DAS", className="kc-label"),
                         html.Div(html.Span("–", className="kc-num"), className="kc-value"),
                         html.Div("Data hujan tidak terbaca", className="kc-sub")], className="card kpi-card")

    info, forecast = snap["model"] or {}, snap["forecast"]
    metric, stat, value = str(info.get("selection_metric") or "").upper(), info.get("stat", "median"), info.get("stat_value")
    model = (f"Model {str(info['best_model']).upper()}" if info.get("best_model") else
             f"Model {', '.join(sorted(forecast['model'].unique())).upper()}" if not forecast.empty else "Model –")
    if value is not None and metric == "NSE":
        fill = round(min(max(value, 0.0), 1.0) * 100, 1)
        nse = [html.Div([html.Span(_id(value, 2), className="kc-num"), html.Span(f"NSE {stat}", className="unit")],
                        className="kc-value"),
               html.Div(html.Span(style={"width": f"{fill}%"}), className="fill-bar"),
               html.Div([html.Span("0"), html.Span("1 = sempurna")], className="fill-names"),
               html.Div(f"{model} · {stat} NSE saat seleksi", className="kc-sub"),
               html.Div("Lebih besar, lebih baik", className="kc-hint")]
    elif value is not None:
        nse = [html.Div([html.Span(_id(value, 2), className="kc-num"), html.Span(f"{metric} {stat}", className="unit")],
                        className="kc-value"),
               html.Div(f"{model} · saat seleksi", className="kc-sub")]
    else:
        nse = [html.Div(html.Span("–", className="kc-num"), className="kc-value"),
               html.Div(f"{model} · statistik seleksi belum tersimpan", className="kc-sub")]
    return [pos, rain, html.Div([html.Span("Keandalan model prakiraan", className="kc-label"), *nse],
                                className="card kpi-card")]


def _attention_card(i, a):
    """Satu pos yang perlu perhatian: angka utama, papan duga, tindakan, tautan ke grafiknya.

    TMA sekarang di bawah angka utama diwarnai sesuai status pos sekarang.
    """
    r, now = a["row"], a["now_level"]
    big, line = card_figure(a, UNIT, RISE_THRESHOLD_CM, REPORT["trend_steps"])
    peak_line = line.startswith("puncak dalam")  # angka besar = puncak prakiraan: "84,8 cm · +12 jam"
    if peak_line:  # keterangan kecil di bawahnya: TMA sekarang (+ kelanjutan "menuju Siaga ..." kalau ada)
        extra = line.split(" · ", 1)[1] if " · " in line else None
        line = [html.B(f"{_id(r['now'])} cm" if r["now"] is not None else "–", className=f"ac-now s{now or 0}"),
                " · sekarang"] + ([f" · {extra}"] if extra else [])
    river = _river(r["station"]) or (f"Aliran {r['aliran']}" if r["aliran"] else "")
    return html.Div([
        html.Div([html.Div([html.Span(f"#{i} · {river}" if river else f"#{i}", className="ac-rank"),
                            html.H3(r["label"])])], className="ac-head"),
        html.Div([html.Span(big, className="ac-big"), html.Span(" cm", className="ac-unit") if big != "–" else None,
                  html.Span(f" · +{r['peak_h']} {UNIT}", className="ac-when") if peak_line else None]),
        html.Div(line, className="ac-line"),
        _gauge(r, show_limit=3),
        html.Div([html.Span("TINDAKAN", className="ac-k"), html.P(a["action"])], className="ac-act"),
        dcc.Link(["Lihat detail pos ini ", html.Span("→", className="arrow")], href=_station_href(r["station"]),
                 className="ac-link"),
    ], className="card attn-card")


def _attention(snap, rows, horizons, now):
    """(judul, subjudul, isi) kartu "Perlu tindakan" (ada yang di atas Normal) atau "Perlu dipantau" (semua Normal)."""
    needed = attention(assess(rows, snap, horizons, REPORT_CFG))
    acting = any(_severity(a["row"]) < 4 for a in needed)
    body = []
    stale = stale_note(now, snapshot_as_of(snap), UNIT)
    if stale:
        body.append(html.P(stale, className="br-warn"))
    if not needed:
        return ("Tidak ada pos yang perlu tindakan", "Semua pos Normal dan tidak ada sinyal kenaikan.",
                body + [html.P("Lanjutkan pemantauan rutin.", className="br-none")])
    # "Perlu tindakan" hanya menghitung pos yang sudah/akan Siaga; yang cuma naik tetap Normal masuk "dipantau"
    n_act = sum(_severity(a["row"]) < 4 for a in needed)
    title = (f"Perlu tindakan · {n_act} dari {len(rows)} pos" if acting else
             f"Perlu dipantau · {len(needed)} dari {len(rows)} pos")
    watching = len(needed) - n_act
    sub = ("Diurutkan dari yang paling parah" + (f"; {watching} pos lain perlu dipantau." if watching else ".")
           if acting else
           "Semua masih Normal, tetapi diprakirakan naik. Diurutkan dari yang paling perlu perhatian.")
    body.append(html.Div(_gauge_key(), className="legend attn-legend"))
    body.append(html.Div([_attention_card(i, a) for i, a in enumerate(needed[:ATTN_CARDS], 1)],
                         className="attn-grid"))
    rest = needed[ATTN_CARDS:]
    if rest:
        body.append(html.P(f"Juga perlu perhatian: {', '.join(a['row']['label'] for a in rest)}. "
                           "Alasan dan tindakannya ada di laporan lengkap.", className="br-more"))
    return title, sub, body


def _row_hover(r, value, when):
    """Teks hover baris status: TMA pada waktu yang dipilih, puncak prakiraan, dan batas siaga pos."""
    lines = [f"{r['label']}: TMA {_fmt_cm(value)} ({when})"]
    if r["peak"] is not None:
        lines.append(f"Puncak prakiraan: {_fmt_cm(r['peak'])} pada +{r['peak_h']} {UNIT}")
    limits = " · ".join(f"Siaga {lvl} > {r['limits'][lvl]:g} cm" for lvl in (3, 2, 1) if lvl in r["limits"])
    if limits:
        lines.append(limits)
    return chr(10).join(lines)


def _matrix(rows, horizons, horizon, selected):
    """Status per pos: satu baris per pos dengan papan duga mini dan jarak ke ambang siaga berikutnya pada waktu
    `horizon`. Urutan: yang paling dekat (atau sudah melewati semua) ambang dulu, pos tanpa ambang di akhir."""
    when = "sekarang" if not horizon else f"+{horizon} {UNIT}"

    def at(r, h):
        return r["now"] if not h else r["forecasts"].get(h)

    def ahead(r):
        """(Siaga, batas cm, sisa cm) ambang terdekat di atas TMA pada `horizon`; (None, None, 0) kalau sudah
        melewati semuanya; None kalau tanpa ambang atau angka."""
        value = at(r, horizon)
        if value is None or not r["limits"]:
            return None
        above = [(cm, lvl) for lvl, cm in r["limits"].items() if cm > value]
        if not above:
            return None, None, 0.0
        cm, lvl = min(above)
        return lvl, cm, round(cm - value, 1)

    ordered = sorted(rows, key=lambda r: (ahead(r) is None, ahead(r)[2] if ahead(r) else 0))
    items = [html.Div(f"Diurutkan dari yang paling dekat ambang selanjutnya · {when}", className="mx-lead")]
    for r in ordered:
        value, nxt = at(r, horizon), ahead(r)
        sub = _river(r["station"]) or (f"Aliran {r['aliran']}" if r["aliran"] else "")
        if nxt is None:
            note, bar = html.Span("Tanpa ambang Siaga" if not r["limits"] else "–", className="mx-none"), None
        else:
            lvl, cm, left = nxt
            text = (f"{num_id(left)} cm lagi ke Siaga {lvl} ({cm:g} cm)" if lvl else
                    f"Sudah di atas Siaga 1 ({r['limits'][1]:g} cm)" if 1 in r["limits"] else "Sudah di atas semua ambang")
            note, bar = html.Span(text, className="mx-gap"), _gauge(r, at=value, when=when)
        items.append(html.Button([
            html.Span(html.Span(r["label"], className="mx-name"), className="mx-title"),
            html.Span(sub, className="mx-sub"),
            html.Div([bar, note] if bar is not None else [note], className="mx-mid"),
            html.Span(html.Span(f"{_id(value)} cm" if value is not None else "–", className="mx-val"), className="mx-end"),
        ], id={"type": "row", "station": r["station"]}, n_clicks=0, type="button", title=_row_hover(r, value, when),
            className="mx-row mx-item" + (" sel" if r["station"] == selected else "")))
    return items


def _picked_box(row, horizon):
    """Kunci papan duga di kaki kartu status (sama dengan kartu "Perlu dipantau")."""
    return html.Div(_gauge_key("TMA sekarang" if not horizon else f"TMA +{horizon} {UNIT}"), className="legend attn-legend")


def _limit_ahead(row):
    """(Siaga, batas cm) berikutnya di atas puncak prakiraan (TMA sekarang kalau tanpa prakiraan); yang sudah
    terlampaui puncak dilewati. None kalau tanpa ambang atau sudah di atas semuanya."""
    ref = row["peak"] if row["peak"] is not None else row["now"]
    above = [(cm, lvl) for lvl, cm in row["limits"].items() if ref is not None and cm >= ref]
    if not above:
        return None
    cm, lvl = min(above)
    return lvl, cm


def _chart_stats(row, as_of):
    """Tiga angka di atas grafik: TMA sekarang, puncak prakiraan, dan batas siaga berikutnya di atas puncak."""
    if row is None:
        return None
    when = (f" · {as_of.day} {BULAN[as_of.month - 1]} {as_of:%H:%M}"
            if as_of is not None and GRANULARITY == "hourly" else "")
    stats = [html.Div([html.Span(f"TMA sekarang{when}", className="k-label"),
                       html.Div(f"{_id(row['now'])} cm" if row["now"] is not None else "–", className="k-value")],
                      className="kpi")]
    if row["peak"] is not None:
        delta = f" ({_id(row['peak'] - row['now'], sign=True)} cm)" if row["now"] is not None else ""
        stats.append(html.Div([html.Span(f"Puncak prakiraan · +{row['peak_h']} {UNIT}", className="k-label"),
                               html.Div([f"{_id(row['peak'])} cm", html.Span(delta, className="unit")],
                                        className="k-value")], className="kpi"))
    ahead = _limit_ahead(row)
    if ahead:
        stats.append(html.Div([html.Span(f"Batas Siaga {ahead[0]}", className="k-label"),
                               html.Div([f"{_id(ahead[1])} cm"], className="k-value")], className="kpi"))
    return stats


def _footer_line(snap):
    """Baris kecil di kaki halaman: waktu data terakhir, model dan cara status dihitung."""
    as_of = snapshot_as_of(snap)
    fresh = ("Data terakhir: belum ada data" if as_of is None else
             f"Data terakhir {as_of:%H:%M} WIB, {_date_id(as_of)}" if GRANULARITY == "hourly" else
             f"Data terakhir {_date_id(as_of)}")
    info = snap["model"] or {}
    if info.get("best_model"):
        note = selection_note(info)
        model = f"Model {str(info['best_model']).upper()}" + (f" · {note.replace('.', ',')}" if note else "")
    elif not snap["forecast"].empty:
        model = f"Model {', '.join(sorted(snap['forecast']['model'].unique())).upper()} · dari forecast_output"
    else:
        model = "Model –"
    return [html.Span(fresh), html.Span(model), html.Span("Status mengikuti ambang Siaga 4–1 tiap pos")]


def _gauge(row, show_limit=None, at=None, when="sekarang"):
    """Papan duga mini (figures.gauge): zona siaga pos, tanda TMA sekarang, garis biru ke puncak prakiraan.

    `show_limit` (mis. 3): tulis batas bawah siaga itu (cm) di bawah awal zonanya."""
    g = gauge(row, at)
    if g is None:
        return html.Div(html.Span("Ambang belum ada" if not row["limits"] else "–", className="dash"),
                        className="gauge none")
    now, peak = g["now"], g["peak"]
    marks = []
    if now is not None and peak is not None:
        a, b = sorted((now, peak))
        marks.append(html.Span(className="g-run", style={"left": f"{a}%", "width": f"{b - a}%"}))
    if now is not None:
        marks.append(html.Span(className="g-now", style={"left": f"{now}%"}))
    if peak is not None:  # titik puncak terakhir = paling depan, supaya tetap terlihat saat menimpa tanda TMA
        marks.append(html.Span(className="g-peak", style={"left": f"{peak}%"}))
    zones = html.Div([html.Span(className=f"gz z{lvl}", style={"left": f"{x0}%", "width": f"{x1 - x0}%"})
                      for lvl, x0, x1 in g["zones"]], className="g-zones")
    track = [html.Div([zones, *marks], className="g-track")]
    start = next((x0 for lvl, x0, _ in g["zones"] if lvl == show_limit), None)
    if start is not None and show_limit in row["limits"]:
        track.append(html.Div(html.Span([f"Siaga {show_limit}", html.Br(), f"{row['limits'][show_limit]:g} cm"],
                                           style={"left": f"{start}%"}),
                              className="g-limit"))
    return html.Div(track, className="gauge",
                    title=_row_hover(row, row["now"] if at is None else at, when))


def _fmt_cm(value):
    return "–" if value is None else f"{value:.1f} cm"


def _gauge_key(now_label="TMA sekarang"):
    """Kunci papan duga; tiap contoh adalah tanda yang dijelaskannya."""
    return ([html.Span([html.I(className=f"key-zone z{lvl}"), f"Siaga {lvl}"]) for lvl in (4, 3, 2, 1)]
            + [html.Span([html.I(className="key-now"), now_label]),
               html.Span([html.I(className="key-peak"), "Puncak prakiraan"])])


def _horizon_options(snap):
    hs = _horizons(snap) if snap else []
    return [{"label": "Sekarang", "value": 0}] + [{"label": f"+{h} {UNIT}", "value": h} for h in hs]


def _station_href(station):
    return f"{DETAIL_PATH}?{urlencode({'nama': station})}"


def _delta(value, base):
    """'▲ +2,3' / '▼ −4,2' / '0,0': selisih prakiraan terhadap TMA sekarang; None kalau salah satunya tak ada."""
    if value is None or base is None:
        return None
    diff = round(value - base, 1)
    if diff == 0:
        return "0,0"
    return f"{'▲' if diff > 0 else '▼'} {num_id(diff, sign=True).replace('-', '−')}"


def _station_list(rows, horizons, selected):
    """Kolom kiri "Pilih pos": per aliran, tiap pos satu tautan ?nama= dengan TMA, perubahan sampai horizon terakhir
    dan jarak ke batas berikut; pos terpilih diberi garis biru."""
    last = horizons[-1] if horizons else None
    items, group = [], object()
    for r in rows:
        if r["aliran"] != group:
            group = r["aliran"]
            items.append(html.Div(f"ALIRAN {str(group).upper()}" if group else "LAINNYA", className="pl-group"))
        level, limit3 = r["status_by_h"].get(0), r["limits"].get(3)
        fill = (min(max(r["now"] / limit3, 0.0), 1.0) * 100
                if r["now"] is not None and limit3 and limit3 > 0 else 0)
        nxt = next_limit(r)
        caption = (f"{num_id(nxt[2])} cm ke S{nxt[0]}" if nxt else "Awas" if level == 1 else
                   "Normal" if level == 4 else "–")
        change = _delta(r["forecasts"].get(last), r["now"])
        items.append(dcc.Link([
            html.Div([html.Span([_dot(level), html.Span(r["label"], className="pl-name")], className="pl-who"),
                      html.Span(num_id(r["now"]) if r["now"] is not None else "–", className="pl-now"),
                      html.Span(change or "", className="pl-change" + (" down" if change and "▼" in change else ""))],
                     className="pl-line"),
            html.Div(html.Span(style={"width": f"{fill}%"}), className=f"pl-bar s{level or 0}"),
            html.Div(caption, className="pl-cap"),
        ], href=_station_href(r["station"]), className="pl-item sel" if r["station"] == selected else "pl-item"))
    legend = [html.Div([html.Span([_dot(lvl), name], className="map-legend-item")
                        for lvl, name in ((4, "Siaga 4"), (3, "Siaga 3"), (2, "Siaga 2"), (1, "Siaga 1"))],
                       className="pl-legend"),
              html.Div(f"▲▼ = perubahan pada +{last} {UNIT}" if last else "", className="pl-legend sub")]
    return [html.Div([html.H2("Pilih pos"), html.Div(f"TMA sekarang, perubahan {last} {UNIT}, dan jarak ke ambang selanjutnya.",
                                                      className="sub")], className="pl-head"),
            html.Div(items, className="pl-items"), html.Div(legend, className="pl-foot")]


def _outlook(row, horizons):
    """(status, nama status, keterangan): status pos paling parah selama horizon prakiraan (atau status di horizon
    terakhir kalau membaik), dengan waktunya kalau lebih parah dari sekarang."""
    now = row["status_by_h"].get(0)
    graded = [(row["status_by_h"][h], h) for h in horizons if h in row["status_by_h"]]
    if now is None or not graded:
        return None
    worst, at = min(graded)
    if worst < now:
        return worst, _status_text(worst), f"pada +{at} {UNIT}"
    if graded[-1][0] > now:
        return graded[-1][0], _status_text(graded[-1][0]), ""
    return now, _status_text(now), ""


def _detail_head(row, horizons, as_of):
    """Kartu judul pos terpilih: aliran, nama, sungai dan koordinat, status, dan empat angka utama."""
    if row is None:
        return html.P("Pilih pos di daftar kiri atau di peta.", className="empty")
    level = row["status_by_h"].get(0)
    river = _river(row["station"])
    where = " · ".join(x for x in (river, f"{row['lat']:.3f}, {row['lon']:.3f}" if row["lat"] is not None else None)
                       if x)
    when = (f" · {as_of:%H:%M}" if as_of is not None and GRANULARITY == "hourly" else "")
    stats = [html.Div([html.Span(f"TMA sekarang{when}", className="ds-k"),
                       html.Div([num_id(row["now"]) if row["now"] is not None else "–",
                                 html.Span(" cm", className="unit")],
                                className=f"ds-v s{level}" if level else "ds-v")], className="dt-stat")]
    peak_level = row["status_by_h"].get(row["peak_h"])  # warna angka puncak = status di jam puncaknya
    if row["peak"] is not None:
        stats.append(html.Div([html.Span(f"Puncak prakiraan · +{row['peak_h']} {UNIT}", className="ds-k"),
                               html.Div([num_id(row["peak"]), html.Span(" cm", className="unit")],
                                        className=f"ds-v s{peak_level}" if peak_level else "ds-v blue")], className="dt-stat"))
    ahead = _limit_ahead(row)
    if ahead:
        stats.append(html.Div([html.Span(f"Batas Siaga {ahead[0]}", className="ds-k"),
                               html.Div([num_id(ahead[1]), html.Span(" cm", className="unit")], className="ds-v")],
                              className="dt-stat"))
    outlook = _outlook(row, horizons)
    if outlook:
        stats.append(html.Div([html.Span(f"Status {horizons[-1]} {UNIT} ke depan", className="ds-k"),
                               html.Div(outlook[1], className="ds-v status"),
                               html.Div(outlook[2], className="ds-sub status")],
                              className=f"dt-stat status s{outlook[0]}"))
    return [html.Div([html.Div([html.Div(f"ALIRAN {str(row['aliran']).upper()}" if row["aliran"] else "POS",
                                         className="dt-eyebrow"),
                                html.H1(row["station"]), html.Div(where, className="dt-where")]),
                      html.Span([_dot(level), f"{SIAGA_NAME[level]} · Siaga {level}"] if level else "Tanpa ambang",
                                className=f"pill big s{level or 0}")], className="dt-title"),
            html.Div(stats, className="dt-stats")]


VG_H = 400  # tinggi papan duga tegak (px)
VG_IN = 18  # tinggi tulisan batas di dalam batang (px)


def _vgauge(row):
    """Papan duga tegak, batang di tengah: zona siaga pos pada skalanya sendiri, kolom air setinggi TMA sekarang,
    garis putus-putus di puncak prakiraan. Batas tiap Siaga (cm) ditulis di dalam batang tepat di garis batasnya;
    penjelasan puncak prakiraan di kiri, TMA sekarang di kanan; legenda semua status di atas."""
    limits = {lvl: row["limits"][lvl] for lvl in (3, 2, 1) if lvl in row["limits"]}
    values = [v for v in (row["now"], *row["forecasts"].values()) if v is not None]
    if not limits or not values:
        return html.P("Batas siaga atau TMA belum tersedia untuk pos ini.", className="empty")
    lo, hi = min([0.0, *values, *limits.values()]), max([*values, *limits.values()])
    lo, hi = lo - (0.04 * (hi - lo) if lo < 0 else 0), hi + 0.14 * (hi - lo)
    y = lambda v: round((1 - (v - lo) / (hi - lo)) * VG_H, 1)  # noqa: E731  px dari atas
    cuts = sorted(limits.items(), key=lambda kv: kv[1])  # naik: Siaga 3, 2, 1
    bands = [html.Span(className=f"vg-band z{lvl}", style={"top": f"{y(end)}px", "height": f"{y(start) - y(end)}px"})
             for lvl, start, end in [(4, lo, cuts[0][1])] + [(lvl, cm, cuts[i + 1][1] if i + 1 < len(cuts) else hi)
                                                              for i, (lvl, cm) in enumerate(cuts)]]
    water = []
    if row["now"] is not None:
        water.append(html.Span(className=f"vg-water s{row['status_by_h'].get(0) or 0}",
                               style={"top": f"{y(row['now'])}px", "bottom": "0"}))
    if row["peak"] is not None:
        water.append(html.Span(className="vg-peak", style={"top": f"{y(row['peak'])}px"}))
    # batas siaga di dalam batang: garis tipis di batasnya, tulisan tepat di atasnya
    inside = []
    for lvl, cm in limits.items():
        inside += [html.Span(className="vg-cut", style={"top": f"{y(cm)}px"}),
                   html.Span(f"{cm:g} cm", className=f"vg-in s{lvl}",
                             style={"top": f"{max(2, y(cm) - VG_IN)}px", "height": f"{VG_IN}px"})]

    def side(kind, label, value, at, tone):
        """Satu label di samping batang, sejajar tinggi aslinya, dengan garis ke batang."""
        text = html.Span([html.Span(label, className="vg-s-k"), html.Span(value, className="vg-s-v")], className="vg-s-t")
        line = html.Span(className="vg-s-line")
        return html.Div([text, line] if kind == "left" else [line, text],
                        className=f"vg-s {kind}" + (f" s{tone}" if tone else ""), style={"top": f"{at}px"})

    left = ([side("left", f"Puncak +{row['peak_h']} {UNIT}", f"{num_id(row['peak'])} cm", y(row["peak"]),
                     row["status_by_h"].get(row["peak_h"]))]
            if row["peak"] is not None else [])
    right = ([side("right", "Sekarang", f"{num_id(row['now'])} cm", y(row["now"]), row["status_by_h"].get(0))]
             if row["now"] is not None else [])
    legend = html.Div([html.Span([html.I(className=f"vg-key z{lvl}"), f"Siaga {lvl}"])
                       for lvl in (4, 3, 2, 1)], className="vg-legend")
    return html.Div([legend,
                     html.Div([html.Div(left, className="vg-side", style={"height": f"{VG_H}px"}),
                               html.Div([*bands, *water, *inside], className="vg-bar", style={"height": f"{VG_H}px"}),
                               html.Div(right, className="vg-side", style={"height": f"{VG_H}px"})], className="vg")],
                    className="vg-wrap")


def _forecast_table(row, horizons):
    """Prakiraan TMA: sekarang dan tiap horizon dengan selisihnya dan statusnya."""
    if row is None or not row["forecasts"]:
        return html.P("Belum ada forecast untuk pos ini.", className="empty")
    lines = [html.Div([html.Span("Sekarang", className="ft-h"),
                       html.Span(f"{num_id(row['now'])} cm" if row["now"] is not None else "–", className="ft-v"),
                       html.Span(className="ft-d"), _status_pill(row["status_by_h"].get(0))], className="ft-row")]
    for h in horizons:
        diff = _delta(row["forecasts"].get(h), row["now"])
        value = row["forecasts"].get(h)
        lines.append(html.Div([html.Span(f"+{h} {UNIT}", className="ft-h"),
                               html.Span(f"{num_id(value)} cm" if value is not None else "–", className="ft-v"),
                               html.Span(diff or "", className="ft-d" + (" down" if diff and "▼" in diff else "")),
                               _status_pill(row["status_by_h"].get(h))], className="ft-row"))
    return [html.Div("Prakiraan TMA", className="ft-title"), *lines]


def _status_pill(level):
    return html.Span(SIAGA_NAME[level] if level else "–", className=f"pill s{level or 0}")


def _end_label(text):
    """'laut, lewat Cengkareng Drain' -> 'Laut · lewat Cengkareng Drain'."""
    return (text.replace("laut, lewat", "Laut · lewat") if text.startswith("laut, lewat")
            else "Laut" if text == "laut" else text[:1].upper() + text[1:])


def _hilir_card(row):
    """Wilayah Cakupan (wilayah hilir pos): satu kartu bernomor per kecamatan (hulu ke hilir) dengan kelurahannya.

    Return (isi kartu, teks untuk disalin)."""
    downstream = hilir_kecamatan(row["station"], HILIR) if row else {}
    if not downstream:
        return html.P("Belum ada data wilayah hilir untuk pos ini.", className="empty"), ""
    info = HILIR[row["station"]]
    total = sum(map(len, downstream.values()))
    cards = [html.Div([
        html.Div([html.Span(str(i), className="hl-no"), html.Span(f"Kec. {kec}", className="hl-name"),
                  html.Span(f"{len(kel)} kel.", className="hl-count")], className="hl-head"),
        html.Div([html.Span(k, className="hl-chip") for k in kel], className="hl-chips")], className="hl-card")
        for i, (kec, kel) in enumerate(downstream.items(), 1)]
    text = "\n".join([f"Wilayah hilir {row['station']} (perkiraan):",
                      *[f"{i}. Kec. {kec}: {', '.join(kel)}" for i, (kec, kel) in enumerate(downstream.items(), 1)]])
    return [
        html.Div([html.Div([html.H2("Wilayah Cakupan"),
                            html.Div(f"{total} kelurahan di {len(downstream)} kecamatan, urut dari hulu ke laut: air dari "
                                     "pos ini melewati nomor 1 lebih dulu.", className="sub")]),
                  html.Button([html.I(className="ico copy"), "Salin daftar kelurahan"], id="dt-copy", n_clicks=0,
                              className="btn outline", type="button")], className="card-head"),
        html.Div([html.Span(f"Hulu · {row['label']}"), html.I(className="hl-line"),
                  html.Span(f"→ {_end_label(info['sampai'])}")], className="hl-route"),
        html.Div(cards, className="hl-grid"),
        html.P(f"Perkiraan: kelurahan dalam {HILIR_BUFFER_M} m dari alur sungai di OpenStreetMap, hulu ke hilir, "
               f"sampai {info['sampai']}. Bukan daftar resmi BPBD.", className="hl-note"),
    ], text


def _map_legend():
    """Legenda peta: titik per status (warna sama dengan titik di peta) dan kotak warna arsiran hilir."""
    items = [html.Span([_dot(lvl), f"Siaga {lvl} · {SIAGA_NAME[lvl]}"], className="map-legend-item")
             for lvl in (4, 3, 2, 1)]
    items.append(html.Span([_dot(0), "Tanpa ambang"], className="map-legend-item"))
    items.append(html.Span([html.I(className="swatch hilir"), "Area hilir pos terpilih"], className="map-legend-item"))
    return items


def _card_head(title, sub, right=None):
    return html.Div([html.Div([html.H2(title), html.Div(sub, className="sub")]), right], className="card-head")


def _chart_levels(snap, station, span):
    """(TMA, catatan) untuk grafik pada rentang `span` (kunci RANGES).

    Rentang yang muat di snapshot dipotong dari sana; yang lebih panjang dibaca per pos (load_history).
    Catatan menjelaskan kalau datanya lebih pendek dari rentang, atau kalau bacaan panjang gagal dan
    grafik kembali ke snapshot.
    """
    label, hours = RANGES[span]
    steps = max(hours // STEP_HOURS, 1)
    levels = snap["levels"]
    if steps > len(levels) and station in levels.columns:
        try:
            levels = load_history(station, steps)
        except Exception:
            logger.exception("Gagal membaca histori %s", station)
            return levels, f"Histori {label} gagal dibaca; yang tampil {len(levels)} {UNIT} terakhir."
    levels = levels.tail(steps)
    if len(levels) and len(levels) < steps * 0.9:
        return levels, f"Data baru tersedia sejak {_date_id(levels.index.min())}."
    return levels, None


def _overview_page():
    """Halaman ringkasan: banner status, tiga angka, pos yang perlu tindakan, peta | status per pos, grafik pos."""
    snap = _snapshot()
    # isi awal dihitung di sini juga, supaya halaman langsung terisi saat dibuka; callback di bawah menyegarkannya
    # (pos/horizon/rentang yang tersimpan di sesi). Tanpa ini halaman tampil kosong sampai callback pertama selesai.
    banner, banner_cls, kpis, attn_title, attn_sub, attn, foot = overview(None)
    map_fig, matrix, picked = draw_map(None, 0, None) if snap else (None, None, None)
    return [
        html.Section(banner, id="banner", className=banner_cls, **{"aria-label": "Status"}),
        html.Div(kpis, id="kpi-row", className="kpi-row"),
        html.Section([
            html.Div([html.Div([html.H2(attn_title, id="attn-title"), html.Div(attn_sub, id="attn-sub", className="sub")]),
                      html.Button([html.I(className="ico doc"), "Laporan lengkap (PDF)"], id="report-brief",
                                  className="btn outline", n_clicks=0)], className="card-head"),
            html.Div(attn, id="attn", className="attn"),
        ], className="card attn-section"),
        html.Div([
            html.Section([
                _card_head("Peta pos TMA", "Klik titik untuk memilih pos; area hilirnya ikut disorot."),
                html.Div(_map_legend(), className="map-legend"),
                # tanpa scrollZoom: sumbu peta fixedrange, jadi wheel di atas peta hanya menahan scroll halaman
                dcc.Graph(id="map", figure=map_fig or blank_figure(),
                          config={"displayModeBar": False, "scrollZoom": False, "responsive": True}),
            ], className="card map-card"),
            html.Section([
                html.Div([html.H2("Status per pos"), html.Div("Pilih pos untuk menyorot area hilirnya di peta.", className="sub")],
                         className="card-head mx-head"),
                html.Div(dcc.RadioItems(id="horizon", options=_horizon_options(snap), value=0, className="seg",
                                        inputClassName="opt-input", persistence=True, persistence_type="session"),
                         className="mx-switch"),
                html.Div(picked, id="picked", className="mx-note"),
                html.Div(matrix, id="matrix", className="matrix"),
            ], className="card matrix-card"),
        ], className="row row-a"),
        html.Div(foot, id="foot", className="foot"),
    ]


def _detail_page(search=""):
    """Halaman detail: daftar pos di kiri; di kanan judul pos dan empat angkanya, papan duga tegak | peta hilir,
    lalu wilayah cakupan (hilir). Pos dari ?nama=. Isi awal dihitung di sini supaya halaman langsung terisi."""
    snap = _snapshot()
    lst, head, gauge_, table, dmap_fig, hilir, copy_text = (
        detail_view(search, None, None) if snap else (None, None, None, None, None, None, ""))
    chart_fig, chart_note, chart_title, chart_stats = (
        draw_chart(search, "3d", None, None) if snap else (None, "", None, None))
    return [
        dcc.Store(id="detail-mounted"),  # Input di dalam halaman: detail_view pasti jalan saat halaman dibuka
        dcc.Store(id="dt-copy-text", data=copy_text),
        html.Div([
            html.Aside(lst, id="dt-list", className="card pl-card"),
            html.Div([
                html.Section(head, id="dt-head", className="card dt-head"),
                html.Div([
                    html.Section([_card_head("Posisi air terhadap batas siaga",
                                             "Status sekarang dan prakiraan sampai horizon terakhir."),
                                  html.Div(gauge_, id="dt-gauge", className="dt-gauge"),
                                  html.Div(table, id="dt-table", className="ft")], className="card gauge-card"),
                    html.Section([_card_head("Lokasi dan aliran ke hilir",
                                             "Area yang disorot dilalui air dari pos ini sampai laut."),
                                  dcc.Graph(id="dmap", figure=dmap_fig or blank_figure(),
                                            config={"displayModeBar": False, "scrollZoom": False,
                                                    "responsive": True})], className="card map-card"),
                ], className="row dt-row"),
                html.Section([
                    html.Div([html.Div([html.H2(chart_title or "Grafik TMA", id="st-title"),
                                        html.Div("Mengikuti pos yang dipilih di daftar atau peta.", className="sub"),
                                        html.Div([html.Span([html.I(className="ck-line solid"), "terukur"]),
                                                  html.Span([html.I(className="ck-line dashed"), "prakiraan"])],
                                                 className="chart-key")]),
                        html.Div([dcc.RadioItems(id="range", options=[{"label": label, "value": key}
                                                                      for key, (label, _) in RANGES.items()],
                                                 value="3d", className="seg", inputClassName="opt-input",
                                                 persistence=True, persistence_type="session"),
                                  html.Span(chart_note, id="range-note", className="range-note")], className="range-wrap")],
                             className="card-head"),
                    html.Div(chart_stats, id="st-kpis", className="kpis"),
                    dcc.Loading(dcc.Graph(id="chart", figure=chart_fig or blank_figure(),
                                          config={"displayModeBar": False, "responsive": True}),
                                type="dot", color="#1d5fbf", parent_className="chart-wrap", delay_show=300),
                ], className="card station-card", id="chart-card"),
                html.Section(hilir, id="dt-hilir", className="card hilir-card"),
            ], className="dt-main"),
        ], className="dt-layout"),
    ]


def serve_layout():
    return html.Div([
        dcc.Location(id="url", refresh="callback-nav"),
        html.Header(html.Div([
            html.Div([
                html.Div([html.Img(src=app.get_asset_url("mark.svg"), alt="", className="mark"),
                          html.Span("Flood Forecast", className="brand"),
                          html.Span(f"Jakarta · {len(STATIONS)} pos TMA", className="scope"),
                          *([html.Span(DEMO, className="demo-tag")] if DEMO else [])], className="brand-row"),
                html.Nav([dcc.Link("Ringkasan", href="/", id="nav-overview", className="nav-link"),
                          dcc.Link("Detail pos", href=DETAIL_PATH, id="nav-detail", className="nav-link")],
                         className="nav"),
            ], className="bar-left"),
            html.Div([html.Span(id="status", className="stamp"),
                      html.Button([html.I(className="ico dl"), "Unduh laporan PDF"], id="report",
                                  className="btn outline", n_clicks=0),
                      html.Button(html.I(className="ico refresh"), id="reload", className="btn outline icon",
                                  n_clicks=0, title="Muat ulang", **{"aria-label": "Muat ulang"})],
                     className="bar-right"),
        ], className="column bar"), className="topbar"),
        html.Main(id="page", className="column"),
        html.Footer(SOURCES, className="column sources"),
        dcc.Store(id="version"),
        dcc.Store(id="picked-station", storage_type="session"),  # pos terpilih di peta/tabel, dibawa antarhalaman
        dcc.Download(id="report-file"),
        dcc.Interval(id="tick", interval=REFRESH_SECONDS * 1000),
    ], className="frame")


app.layout = serve_layout


@app.callback(Output("page", "children"), Output("nav-overview", "className"), Output("nav-detail", "className"),
              Input("url", "pathname"), State("url", "search"))
def route(path, search):
    """Halaman menurut path; ganti pos di halaman detail hanya mengubah ?nama=, tanpa membangun ulang halaman."""
    if path == DETAIL_PATH:
        return _detail_page(search), "nav-link", "nav-link on"
    return _overview_page(), "nav-link on", "nav-link"


def _search_station(search, rows):
    """Pos dari ?nama=; pos default (paling parah) kalau kosong atau tidak dikenal."""
    station = (parse_qs((search or "").lstrip("?")).get("nama") or [None])[0]
    return station if any(r["station"] == station for r in rows) else _default_station(rows)


@app.callback(Output("version", "data"), Input("reload", "n_clicks"), Input("tick", "n_intervals"))
def reload(_, __):
    """Satu pintu baca ulang: tombol Muat ulang memaksa BigQuery, interval memakai cache 30 detik."""
    _snapshot(force=ctx.triggered_id == "reload")
    return datetime.now().isoformat()


@app.callback(Output("horizon", "options"), Input("version", "data"), prevent_initial_call=True)
def refresh_horizons(_):
    snap = _snapshot()
    return _horizon_options(snap) if snap else no_update


@app.callback(Output("status", "children"), Input("version", "data"))
def stamp(_):
    snap = _snapshot()
    return NO_BQ if snap is None else _data_stamp(snap, datetime.now(WIB).replace(tzinfo=None))


@app.callback(
    Output("banner", "children"), Output("banner", "className"), Output("kpi-row", "children"),
    Output("attn-title", "children"), Output("attn-sub", "children"), Output("attn", "children"),
    Output("foot", "children"),
    Input("version", "data"),
)
def overview(_):
    snap = _snapshot()
    if snap is None:
        return html.P(NO_BQ, className="empty"), "banner", None, "Perlu tindakan", "", html.P(NO_BQ, className="empty"), None
    now = datetime.now(WIB).replace(tzinfo=None)
    rows, horizons = _rows(snap), _horizons(snap)
    cls, banner = _banner(snap, rows, horizons)
    title, sub, body = _attention(snap, rows, horizons, now)
    return banner, cls, _kpi_cards(snap, rows), title, sub, body, _footer_line(snap)


def _report():
    """Laporan PDF dari snapshot yang sama dengan yang tampil: temuan, pos yang perlu perhatian, tindakan."""
    snap = _snapshot()
    if snap is None:
        return no_update
    now = datetime.now(WIB).replace(tzinfo=None)
    rows, horizons = _rows(snap), _horizons(snap)
    pdf = build_report(snap, rows, horizons, now, _finding(rows, horizons), REPORT_CFG, SOURCES)
    return dcc.send_bytes(pdf, f"laporan-banjir-{now:%Y%m%d-%H%M}.pdf")


# dua callback, bukan satu dengan dua Input: tombol di kartu laporan hanya ada di halaman ringkasan,
# dan callback tidak jalan selama salah satu Input-nya tidak ada di halaman. Cek n_clicks wajib:
# tombol yang baru disisipkan route tetap memicu callback-nya walau prevent_initial_call
@app.callback(Output("report-file", "data"), Input("report", "n_clicks"), prevent_initial_call=True)
def download_report(clicks):
    return _report() if clicks else no_update


@app.callback(Output("report-file", "data", allow_duplicate=True), Input("report-brief", "n_clicks"),
              prevent_initial_call=True)
def download_report_brief(clicks):
    return _report() if clicks else no_update


def _clicked_station(click):
    try:
        return click["points"][0]["customdata"]
    except (TypeError, KeyError, IndexError):
        return None


@app.callback(
    Output("picked-station", "data"), Input("map", "clickData"),
    Input({"type": "row", "station": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def pick(click, _rows):
    """Pos terpilih dari klik titik di peta, baris tabel status."""
    trigger = ctx.triggered_id
    if trigger == "map":
        return _clicked_station(click) or no_update
    # komponen yang baru disisipkan ulang (refresh) memicu callback dengan n_clicks 0: bukan klik
    if isinstance(trigger, dict) and ctx.triggered[0]["value"]:
        return trigger["station"]
    return no_update


@app.callback(Output("url", "search"), Input("dmap", "clickData"), prevent_initial_call=True)
def pick_from_detail_map(click):
    station = _clicked_station(click)
    return f"?{urlencode({'nama': station})}" if station else no_update


def _chosen(rows, picked):
    """Pos terpilih: yang disimpan kalau masih ada, kalau tidak pos default (paling parah)."""
    return picked if any(r["station"] == picked for r in rows) else _default_station(rows)


@app.callback(
    Output("map", "figure"), Output("matrix", "children"), Output("picked", "children"),
    Input("picked-station", "data"), Input("horizon", "value"), Input("version", "data"),
)
def draw_map(picked, horizon, _):
    """Peta (pos terpilih bercincin, hilirnya diarsir), tabel status per pos dan kotak pos terpilih."""
    snap = _snapshot()
    if snap is None:
        return no_update, html.P(NO_BQ, className="empty"), None
    rows, horizons = _rows(snap), _horizons(snap)
    station = _chosen(rows, picked)
    row = next((r for r in rows if r["station"] == station), None)
    return (map_figure(rows, station, UNIT, horizon), _matrix(rows, horizons, horizon or 0, station),
            _picked_box(row, horizon or 0))


@app.callback(
    Output("chart", "figure"), Output("range-note", "children"), Output("st-title", "children"),
    Output("st-kpis", "children"),
    Input("url", "search"), Input("range", "value"), Input("version", "data"), Input("detail-mounted", "data"),
)
def draw_chart(search, span, _, __):
    """Grafik pos terpilih pada rentangnya, dengan angka TMA sekarang, puncak prakiraan dan jarak ke batas."""
    snap = _snapshot()
    if snap is None:
        return no_update, "", "Grafik TMA", None
    rows = _rows(snap)
    station = _search_station(search, rows)
    row = next((r for r in rows if r["station"] == station), None)
    chart, note = no_update, ""
    if station:
        levels, note = _chart_levels(snap, station, span if span in RANGES else "3d")
        chart = station_figure(levels, snap["forecast"], station, UNIT, row["limits"] if row else None)
    title = f"Grafik TMA · {row['label']}" if row else "Grafik TMA"
    return chart, note, title, _chart_stats(row, snapshot_as_of(snap))


@app.callback(
    Output("dt-list", "children"), Output("dt-head", "children"), Output("dt-gauge", "children"),
    Output("dt-table", "children"), Output("dmap", "figure"), Output("dt-hilir", "children"),
    Output("dt-copy-text", "data"),
    Input("url", "search"), Input("version", "data"), Input("detail-mounted", "data"),
)
def detail_view(search, _, __):
    """Halaman detail: daftar pos (terpilih disorot), judul dan angka pos, papan duga, peta hilir, wilayah hilir."""
    snap = _snapshot()
    if snap is None:
        return html.P(NO_BQ, className="empty"), None, None, None, no_update, None, ""
    rows, horizons = _rows(snap), _horizons(snap)
    station = _search_station(search, rows)
    row = next((r for r in rows if r["station"] == station), None)
    hilir, text = _hilir_card(row)
    return (_station_list(rows, horizons, station), _detail_head(row, horizons, snapshot_as_of(snap)),
            _vgauge(row) if row else None, _forecast_table(row, horizons), map_figure(rows, station, UNIT, 0),
            hilir, text)


# salin daftar kelurahan: di browser, tanpa perjalanan ke server; tombolnya dibuat ulang tiap render (n_clicks 0)
app.clientside_callback(
    """function(n, text) {
        if (!n) { return window.dash_clientside.no_update; }
        try { navigator.clipboard.writeText(text || ""); } catch (e) {}
        return "\u2713 Daftar tersalin";
    }""",
    Output("dt-copy", "children"), Input("dt-copy", "n_clicks"), State("dt-copy-text", "data"),
    prevent_initial_call=True,
)
