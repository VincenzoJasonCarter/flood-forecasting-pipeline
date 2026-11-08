"""Dash app, dua halaman (hasil `make predict-bq`):

/      ringkasan: peta pos + ringkasan, grafik TMA satu pos (rentang 3 hari s.d. 1 tahun), laporan singkat
/pos   detail: papan status siaga per aliran, lalu pos terpilih (?nama=): peta hilir, batas dan prakiraan
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

from .data import (GRANULARITY, REFRESH_SECONDS, REPORT, RISE_THRESHOLD_CM, STATIONS, STEP_HOURS, UNIT, load_history,
                   load_snapshot)
from .figures import (BULAN, HILIR, HILIR_BUFFER_M, SIAGA_NAME, gauge, hilir_kecamatan, map_figure, rain_totals,
                      station_figure, station_rain, station_rows)
from .report import assess, attention, build_report, next_limit, selection_note, snapshot_as_of, stale_note

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
REPORT_CFG = {**REPORT, "unit": UNIT, "rise_cm": RISE_THRESHOLD_CM, "rain_steps": RAIN_STEPS, "hilir": HILIR}
BRIEF_ITEMS = 4  # pos yang dirinci di laporan singkat; sisanya hanya disebut namanya
BRIEF_NEAREST = 3  # tanpa pos yang perlu perhatian: pos yang paling dekat ke batas berikutnya
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


def _num(value):
    """Angka cm satu desimal; None -> tanda hubung abu-abu."""
    if value is None:
        return html.Span("–", className="dash")
    return f"{value:.1f}"


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


def _worst(rows, horizon):
    """(status terparah, pos-pos yang berstatus itu) pada horizon; None kalau tak ada pos yang punya ambang."""
    graded = [r for r in rows if horizon in r["status_by_h"]]
    if not graded:
        return None, []
    level = min(r["status_by_h"][horizon] for r in graded)
    return level, [r for r in graded if r["status_by_h"][horizon] == level]


def _worst_ahead(rows, horizons):
    """(status, horizon, pos-pos) terparah di seluruh horizon forecast; horizon terdekat menang kalau seri."""
    peak = None
    for h in horizons:
        level, at = _worst(rows, h)
        if level is not None and (peak is None or level < peak[0]):
            peak = (level, h, at)
    return peak


def _names(rows):
    return ", ".join(r["label"] for r in rows) if len(rows) <= 2 else f"{len(rows)} pos"


def _status_text(level):
    return SIAGA_NAME[4] if level == 4 else f"Siaga {level}"


def _finding(rows, horizons):
    """Kalimat pertama yang dibaca: pos terparah, sekarang atau di prakiraan, kapan, dan setinggi apa.

    Status sekarang ikut dinilai: pos yang sedang Siaga tetapi diprakirakan surut tidak boleh
    membuat kalimat ini berbunyi "semua Normal".
    """
    if not horizons:
        return NO_FORECAST
    peak = _worst_ahead(rows, horizons)
    now_level, now_at = _worst(rows, 0)
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
        since = f"dari {top['now']:.1f} cm sekarang" if top["now"] is not None else "TMA sekarang tidak terbaca"
        text = (f"{top['station']} diprakirakan Siaga {level} ({SIAGA_NAME[level]}) pada +{h} {UNIT}: "
                f"{top['forecasts'][h]:.1f} cm, {since}.")
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


def _cell(label, value, sub, level=None, lead=False):
    value = value if isinstance(value, list) else [value]
    return html.Div([
        html.Span(label, className="sm-label"),
        html.Div(([_dot(level)] if level else []) + [html.Span(value)],
                 className="sm-value lead" if lead else "sm-value"),
        html.Div(sub, className="sm-sub"),
    ], className="sm-cell")


def _summary(snap, rows, horizons, now):
    """(sel, catatan): tiga angka umum (terburuk ke depan, sekarang, hujan di DAS), lalu kesegaran data
    dan model yang dipakai sebagai teks kecil di bawahnya."""
    peak = _worst_ahead(rows, horizons)
    if peak:
        level, h, at = peak
        sub = (f"{SIAGA_NAME[level]} · {_names(at)}, +{h} {UNIT}" if level < 4
               else f"Siaga 4 · semua pos sampai +{horizons[-1]} {UNIT}")
        ahead = _cell(f"Terburuk dalam {horizons[-1]} {UNIT}", _status_text(level), sub, level, lead=True)
    else:
        ahead = _cell("Terburuk ke depan", "–", "Belum ada forecast", lead=True)

    level, at = _worst(rows, 0)
    normal = sum(r["status_by_h"].get(0) == 4 for r in rows)
    current = (_cell("Sekarang", _status_text(level),
                     f"{SIAGA_NAME[level]} · {_names(at)}" if level < 4 else f"{normal} dari {len(rows)} pos Normal",
                     level)
               if level else _cell("Sekarang", "–", "Ambang siaga belum diisi"))

    totals = rain_totals(snap["rain"], RAIN_STEPS)
    rain = (_cell("Hujan 24 jam di DAS", [f"{totals.mean():.1f}", html.Span(" mm", className="unit")],
                  f"rata-rata {len(totals)} sel grid · terderas {totals.max():.1f} mm")
            if len(totals) else _cell("Hujan 24 jam di DAS", "–", "Data hujan tidak terbaca"))

    forecast, as_of = snap["forecast"], snapshot_as_of(snap)
    if as_of is None:
        fresh = "Data terakhir: belum ada data"
    elif GRANULARITY == "hourly":
        fresh = f"Data terakhir {as_of:%H:%M}, {_date_id(as_of)} · {_ago(now - as_of)}"
    else:
        fresh = f"Data terakhir {_date_id(as_of)} · {_ago(now - as_of)}"

    info = snap["model"] or {}
    if info.get("best_model"):
        note = selection_note(info)
        model = f"Model {str(info['best_model']).upper()}" + (f" · {note}" if note else "")
    elif not forecast.empty:
        model = f"Model {', '.join(sorted(forecast['model'].unique())).upper()} · dari forecast_output"
    else:
        model = "Model –"
    return [ahead, current, rain], [html.Span(fresh), html.Span(model)]


def _brief(snap, rows, horizons, now):
    """Laporan unduhan dalam satu kartu di halaman ringkasan: (subjudul, isi).

    Penilaian sama dengan laporan lengkap (`assess`): pos yang perlu perhatian, paling parah dulu,
    masing-masing dengan alasan utamanya dan tindakan yang disarankan. Peringatan data basi di atas.
    """
    needed = attention(assess(rows, snap, horizons, REPORT_CFG))
    sub = (f"{len(needed)} dari {len(rows)} pos perlu perhatian · paling parah dulu" if needed
           else f"Tidak ada pos yang perlu tindakan khusus dari {len(rows)} pos")
    body = []
    stale = stale_note(now, snapshot_as_of(snap), UNIT)
    if stale:
        body.append(html.P(stale, className="br-warn"))
    if needed:
        body.append(html.Div([html.Span("Pos"), html.Span("Posisi terhadap batas siaga"),
                              html.Span("Alasan utama dan tindakan")], className="br-item br-head"))
        body += [_brief_item(a) for a in needed[:BRIEF_ITEMS]]
    else:
        # kartu kosong diisi data rujukan: pos yang paling dekat ke batas berikutnya
        nearest = sorted((r for r in rows if next_limit(r)), key=lambda r: next_limit(r)[2])[:BRIEF_NEAREST]
        body.append(html.P("Semua pos dalam batas wajar: tidak ada kenaikan status, kenaikan tajam, pos dekat batas, "
                           "hujan lebat, atau sinyal dari hulu. Paling dekat ke batas siaga:", className="br-none"))
        body += [html.Div([_who(r, _status_text(r["status_by_h"][0]), r["status_by_h"][0]),
                           html.Div([_gauge(r), _gauge_caption(r)], className="br-gauge")],
                          className="br-item quiet") for r in nearest]
    rest = needed[BRIEF_ITEMS:]
    if rest:
        body.append(html.P(f"Juga perlu perhatian: {', '.join(a['row']['label'] for a in rest)}. "
                           "Alasan dan tindakannya ada di laporan lengkap.", className="br-more"))
    return sub, body


def _who(row, status, level):
    return html.Div([html.Div([_dot(level), html.Span(row["station"], className="br-title")], className="br-name"),
                     html.Div(status, className="br-status")])


def _brief_item(a):
    r, now, worst = a["row"], a["now_level"], a["worst"]
    status = _status_text(now) if now else ("TMA tidak terbaca" if r["limits"] else "Tanpa ambang")
    if worst is not None and worst < (now or 4):
        status += f" → Siaga {worst} pada +{a['worst_h']} {UNIT}"
    severest = min([s for s in (now, worst) if s is not None], default=None)
    more = len(a["reasons"]) - 1
    return html.Div([
        _who(r, status, severest),
        html.Div([_gauge(r), _gauge_caption(r)], className="br-gauge"),
        html.Div([
            html.P([a["reasons"][0], html.Span(f" · {more} alasan lain", className="br-extra") if more else None],
                   className="br-why"),
            html.P([html.Span("Tindakan", className="br-k"), a["action"]], className="br-act"),
        ], className="br-text"),
    ], className="br-item")


def _gauge(row):
    """Papan duga mini (figures.gauge): zona siaga pos, tanda TMA sekarang, garis biru ke puncak prakiraan."""
    g = gauge(row)
    if g is None:
        return html.Div(html.Span("Ambang belum ada" if not row["limits"] else "–", className="dash"),
                        className="gauge none")
    now, peak = g["now"], g["peak"]
    marks = []
    if now is not None and peak is not None:
        a, b = sorted((now, peak))
        marks.append(html.Span(className="g-run", style={"left": f"{a}%", "width": f"{b - a}%"}))
    if peak is not None:
        marks.append(html.Span(className="g-peak", style={"left": f"{peak}%"}))
    if now is not None:
        marks.append(html.Span(className="g-now", style={"left": f"{now}%"}))
    zones = html.Div([html.Span(className=f"gz z{lvl}", style={"left": f"{x0}%", "width": f"{x1 - x0}%"})
                      for lvl, x0, x1 in g["zones"]], className="g-zones")
    limits = " · ".join(f"Siaga {lvl} > {row['limits'][lvl]:g} cm" for lvl in (3, 2, 1) if lvl in row["limits"])
    return html.Div(html.Div([zones, *marks], className="g-track"), className="gauge",
                    title=f"TMA {_fmt_cm(row['now'])} · {limits}")


def _fmt_cm(value):
    return "–" if value is None else f"{value:.1f} cm"


def _gauge_caption(row):
    """Di bawah papan duga: TMA dan sisanya ke batas berikut di kiri, puncak prakiraan di kanan."""
    nxt, level = next_limit(row), row["status_by_h"].get(0)
    left = [html.B(_fmt_cm(row["now"]))]
    if nxt:
        left.append(f" · {nxt[2]:.1f} cm lagi ke Siaga {nxt[0]}")
    elif level == 1:
        left.append(" · di atas batas Siaga 1")
    right = f"puncak {row['peak']:.1f} cm, +{row['peak_h']} {UNIT}" if row["peak"] is not None else ""
    return html.Div([html.Span(left), html.Span(right, className="g-peak-label")], className="g-caption")


def _gauge_key():
    """Kunci papan duga; tiap contoh adalah tanda yang dijelaskannya."""
    return ([html.Span([html.I(className=f"key-zone z{lvl}"), _status_text(lvl)]) for lvl in (4, 3, 2, 1)]
            + [html.Span([html.I(className="key-now"), "TMA sekarang"]),
               html.Span([html.I(className="key-peak"), "Puncak prakiraan"])])


def _horizon_options(snap):
    hs = _horizons(snap) if snap else []
    return [{"label": "Sekarang", "value": 0}] + [{"label": f"+{h} {UNIT}", "value": h} for h in hs]


def _board_head(horizons, horizon):
    cls = lambda h: "bd-num on" if h == horizon else "bd-num"  # noqa: E731
    return [html.Span("Pos", className="bd-name"), html.Span("Posisi terhadap batas siaga", className="bd-gauge"),
            html.Span("Sekarang", className=cls(0))] + [html.Span(f"+{h} {UNIT}", className=cls(h)) for h in horizons]


def _station_href(station):
    return f"{DETAIL_PATH}?{urlencode({'nama': station})}"


def _board(rows, horizons, horizon, selected=None):
    """Satu baris per pos, dikelompokkan per aliran; tiap baris tautan ?nama= ke pos itu, `selected` disorot."""
    items, group = [], object()
    for r in rows:
        if r["aliran"] != group:
            group = r["aliran"]
            items.append(html.Div(f"Aliran {group}" if group else "Lainnya", className="bd-group"))
        cells = []
        for h in [0] + horizons:
            value = r["now"] if h == 0 else r["forecasts"].get(h)
            level = r["status_by_h"].get(h)
            cls = f"bd-num s{level}" if level in (1, 2, 3) else "bd-num"
            cells.append(html.Span(html.Span(_num(value), className="bd-val"),
                                   className=cls + (" on" if h == horizon else "")))
        label = html.Div([
            html.Span([_dot(r["status_by_h"].get(horizon)),
                       html.Span([html.Span(r["station"], className="full"), html.Span(r["label"], className="short")],
                                 className="bd-title")], className="bd-name"),
            html.Span(_gauge(r), className="bd-gauge"),
            *cells,
        ], className="bd-line")
        items.append(dcc.Link(label, href=_station_href(r["station"]),
                              className="bd-row on" if r["station"] == selected else "bd-row"))
    return items


def _station_head(row):
    if row is None:
        return "Pilih pos", ""
    where = f"Aliran {row['aliran']} · " if row["aliran"] else ""
    river = (HILIR.get(row["station"]) or {}).get("sungai")
    if river and river != row["station"]:
        where += f"Kali {river} · "
    coords = f"≈ {row['lat']:.3f}, {row['lon']:.3f}" if row["lat"] is not None else "koordinat belum diisi"
    return row["station"], f"{where}{coords}"


def _kpis(row, rain_24h):
    """TMA sekarang (dengan statusnya) dan hujan 24 jam, di kanan judul kartu pos."""
    if row is None:
        return None
    level = row["status_by_h"].get(0)
    kpis = [html.Div([
        html.Span("TMA sekarang", className="k-label"),
        html.Div([_num(row["now"]), html.Span(" cm", className="unit")], className="k-value"),
        html.Div([_dot(level), f"Siaga {level} · {SIAGA_NAME[level]}"], className="badge") if level else None,
    ], className="kpi")]
    if rain_24h is not None:
        kpis.append(html.Div([
            html.Span("Hujan 24 jam", className="k-label"),
            html.Div([f"{rain_24h:.1f}", html.Span(" mm", className="unit")], className="k-value"),
            html.Div("di sel model", className="k-sub"),
        ], className="kpi"))
    return kpis


def _detail(row, horizons):
    """Batas siaga, prakiraan dan wilayah hilir pos, di kanan peta halaman detail."""
    if row is None:
        return html.P("Pilih pos di papan status atau di peta.", className="empty")
    blocks = []
    limits = [html.Div([
        html.Span(f"Siaga {lvl} · {SIAGA_NAME[lvl]}", className="kv-k"),
        html.Span([f"> {row['limits'][lvl]:g}", html.Span(" cm", className="unit")], className="kv-v"),
        html.Span(_gap(row["now"], row["limits"][lvl]), className="kv-d"),
    ], className="kv") for lvl in (3, 2, 1) if lvl in row["limits"]]
    if limits:
        blocks.append(html.Div([html.Div("Batas siaga", className="sub-title"), *limits], className="block"))

    forecasts = [html.Div([
        html.Span(f"+{h} {UNIT}", className="kv-k"),
        html.Span([_num(row["forecasts"].get(h)), html.Span(" cm", className="unit")], className="kv-v"),
        html.Span(_change(row, h), className="kv-d"),
    ], className="kv") for h in horizons]
    blocks.append(html.Div([html.Div("Prakiraan (selisih dari sekarang)", className="sub-title"), *forecasts],
                           className="block") if forecasts else html.P("Belum ada forecast untuk pos ini.",
                                                                       className="empty"))
    hilir = _hilir_block(row["station"])
    if hilir:
        blocks.append(hilir)
    return blocks


def _hilir_block(station):
    """Kecamatan dan kelurahan di bantaran hilir pos (hilir.json), lebar penuh di bawah batas dan prakiraan."""
    downstream = hilir_kecamatan(station)
    if not downstream:
        return None
    info = HILIR[station]
    rows = [html.Div([html.Span(kec, className="hl-kec"), html.Span(", ".join(kel), className="hl-kel")],
                     className="hl-row") for kec, kel in downstream.items()]
    note = (f"Perkiraan: kelurahan dalam {HILIR_BUFFER_M} m dari alur sungai di OpenStreetMap, hulu ke hilir, "
            f"sampai {info['sampai']}. Bukan daftar resmi BPBD.")
    return html.Div([html.Div(f"Wilayah hilir · {sum(map(len, downstream.values()))} kelurahan di "
                              f"{len(downstream)} kecamatan", className="sub-title"), *rows,
                     html.P(note, className="hl-note")], className="block hilir")


def _gap(now, limit):
    if now is None:
        return html.Span("–", className="dash")
    return "terlampaui" if now > limit else f"{limit - now:.1f} cm lagi"


def _change(row, h):
    value, now = row["forecasts"].get(h), row["now"]
    if value is None or now is None:
        return html.Span("–", className="dash")
    change = round(value - now, 1)
    cls = "rise" if change >= RISE_THRESHOLD_CM else ""
    return html.Span(f"▲ {change:+.1f} cm" if cls else f"{change:+.1f} cm" if change else "0.0 cm", className=cls)


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
    """Halaman ringkasan: peta + ringkasan, grafik satu pos dengan filter rentang, laporan singkat."""
    snap = _snapshot()
    rows = _rows(snap) if snap else []
    return [
        html.Div([
            html.Section([
                _card_head("Peta", html.Div(id="map-sub"),
                           html.Div([html.Span("Tampilkan status", className="seg-label"),
                                     dcc.RadioItems(id="horizon", options=_horizon_options(snap), value=0,
                                                    className="seg", inputClassName="opt-input",
                                                    persistence=True, persistence_type="session")],
                                    className="seg-wrap")),
                # tanpa scrollZoom: sumbu peta fixedrange, jadi wheel di atas peta hanya menahan scroll halaman
                dcc.Graph(id="map", config={"displayModeBar": False, "scrollZoom": False, "responsive": True}),
            ], className="card map-card"),
            html.Section([
                html.Div([html.H1("Pantauan banjir Jakarta"), html.P(id="finding", className="finding")],
                         className="exec-head"),
                html.Div(id="summary", className="summary"),
                html.Div(id="summary-meta", className="meta"),
            ], className="card exec-card", **{"aria-label": "Ringkasan"}),
        ], className="row row-a"),
        html.Section([
            _card_head(html.Span(id="st-title"), html.Span(id="st-sub"), html.Div(id="st-kpis", className="kpis")),
            html.Div([
                html.Div([html.Span("Pos", className="seg-label"),
                          dcc.Dropdown(id="pick", options=[{"label": r["station"], "value": r["station"]}
                                                           for r in rows],
                                       value=_default_station(rows), clearable=False, className="pick",
                                       persistence=True, persistence_type="session")], className="pick-wrap"),
                html.Div([html.Span("Rentang", className="seg-label"),
                          dcc.RadioItems(id="range", options=[{"label": label, "value": key}
                                                              for key, (label, _) in RANGES.items()],
                                         value="3d", className="seg", inputClassName="opt-input",
                                         persistence=True, persistence_type="session")], className="seg-wrap"),
                html.Span(id="range-note", className="range-note"),
                dcc.Link("Detail pos →", id="to-detail", href=DETAIL_PATH, className="to-detail"),
            ], className="chart-bar"),
            dcc.Loading(dcc.Graph(id="chart", config={"displayModeBar": False, "responsive": True}),
                        type="dot", color="#1d5fbf", parent_className="chart-wrap", delay_show=300),
        ], className="card station-card"),
        html.Section([
            _card_head("Laporan singkat", html.Div(id="brief-sub"),
                       html.Div([html.Div(_gauge_key(), className="legend"),
                                 html.Button("Laporan lengkap (PDF)", id="report-brief", className="btn",
                                             n_clicks=0)], className="head-right")),
            html.Div(id="brief", className="brief"),
        ], className="card brief-card"),
    ]


def _detail_page():
    """Halaman detail: papan status semua pos, lalu pos terpilih (?nama=): peta hilir | batas, prakiraan, hilir."""
    return [
        dcc.Store(id="detail-mounted"),  # Input di dalam halaman: detail_view pasti jalan saat halaman dibuka
        html.Section([
            _card_head("Papan status", "TMA dalam cm, sekarang dan prakiraan; warna sel = status siaga; "
                       "klik pos untuk rinciannya di bawah", html.Div(_gauge_key(), className="legend")),
            html.Div(id="board-head", className="bd-line bd-head"),
            html.Div(id="board", className="board"),
        ], className="card board-card"),
        html.Div([
            html.Section([
                _card_head(html.Span(id="d-title"), html.Span(id="d-sub")),
                dcc.Graph(id="dmap", config={"displayModeBar": False, "scrollZoom": False, "responsive": True}),
            ], className="card map-card"),
            html.Section(html.Div(id="detail", className="detail"), className="card detail-card"),
        ], className="row row-a"),
    ]


def serve_layout():
    return html.Div([
        dcc.Location(id="url", refresh="callback-nav"),
        html.Header(html.Div([
            html.Div([
                html.Div([html.Img(src=app.get_asset_url("mark.svg"), alt="", className="mark"),
                          html.Span("Flood Forecast", className="brand"),
                          html.Span(f"Jakarta · {len(STATIONS)} pos TMA", className="scope")], className="brand-row"),
                html.Nav([dcc.Link("Ringkasan", href="/", id="nav-overview", className="nav-link"),
                          dcc.Link("Detail pos", href=DETAIL_PATH, id="nav-detail", className="nav-link")],
                         className="nav"),
            ], className="bar-left"),
            html.Div([html.Span(id="status", className="stamp"),
                      html.Button("Unduh laporan PDF", id="report", className="btn", n_clicks=0),
                      html.Button("Muat ulang", id="reload", className="btn", n_clicks=0)], className="bar-right"),
        ], className="column bar"), className="topbar"),
        html.Main(id="page", className="column"),
        html.Footer(SOURCES, className="column sources"),
        dcc.Store(id="version"),
        dcc.Download(id="report-file"),
        dcc.Interval(id="tick", interval=REFRESH_SECONDS * 1000),
    ], className="frame")


app.layout = serve_layout


@app.callback(Output("page", "children"), Output("nav-overview", "className"), Output("nav-detail", "className"),
              Input("url", "pathname"), State("url", "search"))
def route(path, _search):
    """Halaman menurut path; ganti pos di halaman detail hanya mengubah ?nama=, tanpa membangun ulang halaman."""
    if path == DETAIL_PATH:
        return _detail_page(), "nav-link", "nav-link on"
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
    return NO_BQ if _snapshot() is None else f"Diperbarui {datetime.now(WIB):%H:%M} WIB"


@app.callback(
    Output("finding", "children"), Output("summary", "children"), Output("summary-meta", "children"),
    Output("map-sub", "children"), Output("brief-sub", "children"), Output("brief", "children"),
    Input("version", "data"), Input("horizon", "value"),
)
def overview(_, horizon):
    snap = _snapshot()
    if snap is None:
        return NO_BQ, html.P(NO_BQ, className="empty"), "", no_update, "", html.P(NO_BQ, className="empty")
    now = datetime.now(WIB).replace(tzinfo=None)
    rows, horizons = _rows(snap), _horizons(snap)
    when = "sekarang" if not horizon else f"pada +{horizon} {UNIT}"
    map_sub = f"Warna titik = status pos {when} · klik titik untuk grafiknya · arsir = kecamatan di hilir pos terpilih"
    brief_sub, brief = _brief(snap, rows, horizons, now)
    cells, meta = _summary(snap, rows, horizons, now)
    return _finding(rows, horizons), cells, meta, map_sub, brief_sub, brief


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


@app.callback(Output("pick", "value"), Input("map", "clickData"), prevent_initial_call=True)
def pick_from_map(click):
    return _clicked_station(click) or no_update


@app.callback(Output("url", "search"), Input("dmap", "clickData"), prevent_initial_call=True)
def pick_from_detail_map(click):
    station = _clicked_station(click)
    return f"?{urlencode({'nama': station})}" if station else no_update


@app.callback(
    Output("map", "figure"), Output("chart", "figure"), Output("range-note", "children"),
    Output("st-title", "children"), Output("st-sub", "children"), Output("st-kpis", "children"),
    Output("to-detail", "href"),
    Input("pick", "value"), Input("range", "value"), Input("horizon", "value"), Input("version", "data"),
)
def draw(station, span, horizon, _):
    """Halaman ringkasan: peta (pos terpilih ditebalkan) dan grafik pos terpilih pada rentangnya."""
    snap = _snapshot()
    if snap is None:
        return no_update, no_update, "", "Pos", "", None, no_update
    rows = _rows(snap)
    row = next((r for r in rows if r["station"] == station), None)
    cells = ((snap["model"] or {}).get("rain_cells") or {}).get(station)
    rain = station_rain(snap["rain"], cells)
    rain_24h = float(rain.tail(RAIN_STEPS).sum()) if rain is not None else None
    chart, note = no_update, ""
    if station:
        levels, note = _chart_levels(snap, station, span if span in RANGES else "3d")
        chart = station_figure(levels, snap["forecast"], station, UNIT, row["limits"] if row else None)
    title, sub = _station_head(row)
    return (map_figure(rows, station, UNIT, horizon), chart, note, title, sub, _kpis(row, rain_24h),
            _station_href(station) if station else DETAIL_PATH)


@app.callback(
    Output("board-head", "children"), Output("board", "children"), Output("dmap", "figure"),
    Output("d-title", "children"), Output("d-sub", "children"), Output("detail", "children"),
    Input("url", "search"), Input("version", "data"), Input("detail-mounted", "data"),
)
def detail_view(search, _, __):
    """Halaman detail: papan status (pos terpilih disorot), lalu peta hilir dan rincian pos dari ?nama=."""
    snap = _snapshot()
    if snap is None:
        return no_update, html.P(NO_BQ, className="empty"), no_update, "Pos", "", html.P(NO_BQ, className="empty")
    rows, horizons = _rows(snap), _horizons(snap)
    station = _search_station(search, rows)
    row = next((r for r in rows if r["station"] == station), None)
    title, sub = _station_head(row)
    return (_board_head(horizons, 0), _board(rows, horizons, 0, station), map_figure(rows, station, UNIT, 0),
            title, sub, _detail(row, horizons))
