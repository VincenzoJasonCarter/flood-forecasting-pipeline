"""Dash app: ringkasan, laporan singkat, papan status siaga per aliran, peta hujan + pos, dan panel satu pos (hasil `make predict-bq`)."""

import logging
from datetime import datetime, timedelta, timezone

from dash import Dash, Input, Output, ctx, dcc, html, no_update

from .data import GRANULARITY, REFRESH_SECONDS, REPORT, RISE_THRESHOLD_CM, STATIONS, UNIT, load_snapshot
from .figures import (BULAN, HILIR, HILIR_BUFFER_M, SIAGA_NAME, gauge, hilir_kecamatan, map_figure, rain_totals,
                      station_figure, station_rain, station_rows)
from .report import assess, attention, build_report, next_limit, selection_note, snapshot_as_of, stale_note

logger = logging.getLogger(__name__)

FONTS = "https://fonts.googleapis.com/css2?family=Geist:wght@400;500;700&display=swap"

app = Dash(__name__, title="Flood Forecast", external_stylesheets=[FONTS])
server = app.server  # untuk gunicorn kalau nanti di-deploy

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
    """Lima angka umum: terburuk ke depan, sekarang, hujan di DAS, kesegaran data, model yang dipakai."""
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
        fresh = _cell("Data terakhir", "–", "Belum ada data")
    else:
        clock = as_of.strftime("%H:%M") if GRANULARITY == "hourly" else _date_id(as_of)
        sub = f"{_date_id(as_of)} · {_ago(now - as_of)}" if GRANULARITY == "hourly" else _ago(now - as_of)
        fresh = _cell("Data terakhir", clock, sub)

    info = snap["model"] or {}
    if info.get("best_model"):
        model = _cell("Model", str(info["best_model"]).upper(), selection_note(info) or "model terpilih")
    else:
        model = _cell("Model", ", ".join(sorted(forecast["model"].unique())).upper() if not forecast.empty else "–",
                      "dari forecast_output")
    return [ahead, current, rain, fresh, model]


def _brief(snap, rows, horizons, now):
    """Laporan unduhan dalam satu kartu di atas peta: (subjudul, isi).

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


def _board_options(rows, horizons, horizon):
    """Satu opsi RadioItems per pos, dikelompokkan per aliran (judul kelompok = opsi nonaktif)."""
    options, group = [], object()
    for r in rows:
        if r["aliran"] != group:
            group = r["aliran"]
            options.append({"label": html.Div(f"Aliran {group}" if group else "Lainnya", className="bd-group"),
                            "value": f"__group_{group}", "disabled": True})
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
        options.append({"label": label, "value": r["station"]})
    return options


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
    """Batas siaga dan prakiraan pos, dua kolom di bawah grafik."""
    if row is None:
        return html.P("Pilih pos di peta atau di papan status.", className="empty")
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


def serve_layout():
    snap = _snapshot()
    rows = _rows(snap) if snap else []
    return html.Div([
        html.Header(html.Div([
            html.Div([html.Img(src=app.get_asset_url("mark.svg"), alt="", className="mark"),
                      html.Span("Flood Forecast", className="brand"),
                      html.Span(f"Jakarta · {len(STATIONS)} pos TMA", className="scope")], className="brand-row"),
            html.Div([html.Span(id="status", className="stamp"),
                      html.Button("Unduh laporan PDF", id="report", className="btn", n_clicks=0),
                      html.Button("Muat ulang", id="reload", className="btn", n_clicks=0)], className="bar-right"),
        ], className="column bar"), className="topbar"),
        html.Main([
            html.Div([
                html.Div([html.H1("Pantauan banjir Jakarta"), html.P(id="finding", className="finding")],
                         className="title-text"),
                html.Div([html.Span("Tampilkan status", className="seg-label"),
                          dcc.RadioItems(id="horizon", options=_horizon_options(snap), value=0, className="seg",
                                         inputClassName="opt-input")], className="seg-wrap"),
            ], className="title-row"),
            html.Section(id="summary", className="summary card", **{"aria-label": "Ringkasan"}),
            html.Section([
                _card_head("Laporan singkat", html.Div(id="brief-sub"),
                           html.Div([html.Div(_gauge_key(), className="legend"),
                                     html.Button("Laporan lengkap (PDF)", id="report-brief", className="btn",
                                                 n_clicks=0)], className="head-right")),
                html.Div(id="brief", className="brief"),
            ], className="card brief-card"),
            html.Div([
                html.Section([
                    _card_head("Peta", html.Div(id="map-sub")),
                    # tanpa scrollZoom: sumbu peta fixedrange, jadi wheel di atas peta hanya menahan scroll halaman
                    dcc.Graph(id="map", config={"displayModeBar": False, "scrollZoom": False, "responsive": True}),
                ], className="card map-card"),
                html.Section([
                    _card_head(html.Span(id="st-title"), html.Span(id="st-sub"),
                               html.Div(id="st-kpis", className="kpis")),
                    dcc.Graph(id="chart", config={"displayModeBar": False, "responsive": True}),
                    html.Div(id="detail", className="detail"),
                ], className="card station-card"),
            ], className="row row-a"),
            html.Section([
                _card_head("Papan status", "TMA dalam cm, sekarang dan prakiraan; warna sel = status siaga",
                           html.Div(_gauge_key(), className="legend")),
                html.Div(id="board-head", className="bd-line bd-head"),
                dcc.RadioItems(id="station", options=[], value=_default_station(rows), className="board",
                               inputClassName="opt-input"),
            ], className="card board-card"),
            html.Footer(SOURCES, className="sources"),
        ], className="column"),
        dcc.Store(id="version"),
        dcc.Download(id="report-file"),
        dcc.Interval(id="tick", interval=REFRESH_SECONDS * 1000),
    ], className="frame")


app.layout = serve_layout


@app.callback(Output("version", "data"), Input("reload", "n_clicks"), Input("tick", "n_intervals"))
def reload(_, __):
    """Satu pintu baca ulang: tombol Muat ulang memaksa BigQuery, interval memakai cache 30 detik."""
    _snapshot(force=ctx.triggered_id == "reload")
    return datetime.now().isoformat()


@app.callback(Output("horizon", "options"), Input("version", "data"), prevent_initial_call=True)
def refresh_horizons(_):
    snap = _snapshot()
    return _horizon_options(snap) if snap else no_update


@app.callback(
    Output("status", "children"), Output("finding", "children"), Output("summary", "children"),
    Output("board-head", "children"), Output("station", "options"),
    Output("map-sub", "children"), Output("brief-sub", "children"), Output("brief", "children"),
    Input("version", "data"), Input("horizon", "value"),
)
def overview(_, horizon):
    snap = _snapshot()
    if snap is None:
        return (NO_BQ, NO_BQ, html.P(NO_BQ, className="empty"), no_update, no_update, no_update,
                "", html.P(NO_BQ, className="empty"))
    now = datetime.now(WIB).replace(tzinfo=None)
    rows, horizons = _rows(snap), _horizons(snap)
    when = "sekarang" if not horizon else f"pada +{horizon} {UNIT}"
    map_sub = f"Warna titik = status pos {when} · klik titik untuk grafiknya · arsir = kecamatan di hilir pos terpilih"
    brief_sub, brief = _brief(snap, rows, horizons, now)
    return (f"Diperbarui {now:%H:%M} WIB", _finding(rows, horizons), _summary(snap, rows, horizons, now),
            _board_head(horizons, horizon), _board_options(rows, horizons, horizon),
            map_sub, brief_sub, brief)


@app.callback(Output("report-file", "data"), Input("report", "n_clicks"), Input("report-brief", "n_clicks"),
              prevent_initial_call=True)
def download_report(_, __):
    """Laporan PDF dari snapshot yang sama dengan yang tampil: temuan, pos yang perlu perhatian, tindakan."""
    snap = _snapshot()
    if snap is None:
        return no_update
    now = datetime.now(WIB).replace(tzinfo=None)
    rows, horizons = _rows(snap), _horizons(snap)
    pdf = build_report(snap, rows, horizons, now, _finding(rows, horizons), REPORT_CFG, SOURCES)
    return dcc.send_bytes(pdf, f"laporan-banjir-{now:%Y%m%d-%H%M}.pdf")


@app.callback(Output("station", "value"), Input("map", "clickData"), prevent_initial_call=True)
def pick_from_map(click):
    try:
        return click["points"][0]["customdata"]
    except (TypeError, KeyError, IndexError):
        return no_update


@app.callback(
    Output("map", "figure"), Output("chart", "figure"), Output("st-title", "children"),
    Output("st-sub", "children"), Output("st-kpis", "children"), Output("detail", "children"),
    Input("station", "value"), Input("horizon", "value"), Input("version", "data"),
)
def draw(station, horizon, _):
    snap = _snapshot()
    if snap is None:
        return no_update, no_update, "Pos", "", None, html.P(NO_BQ, className="empty")
    rows = _rows(snap)
    row = next((r for r in rows if r["station"] == station), None)
    cells = ((snap["model"] or {}).get("rain_cells") or {}).get(station)
    rain = station_rain(snap["rain"], cells)
    rain_24h = float(rain.tail(RAIN_STEPS).sum()) if rain is not None else None
    chart = (station_figure(snap["levels"], snap["forecast"], station, UNIT, row["limits"] if row else None)
             if station else no_update)
    title, sub = _station_head(row)
    return (map_figure(rows, station, UNIT, horizon), chart,
            title, sub, _kpis(row, rain_24h), _detail(row, _horizons(snap)))
