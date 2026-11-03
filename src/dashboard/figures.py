"""Pure builders for the dashboard: per-station rows, catchment rain, the Jakarta map and the station chart."""

import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

INK = "#0a0a0a"
MUTED = "#6b6b6b"
GRID = "#ebebeb"
LEVEL = "#1d5fbf"     # satu-satunya hue data: garis TMA dan prakiraannya
FONT = '"Geist", Inter, system-ui, sans-serif'
RIVER = "#a9c1e3"     # alur sungai pos lain; alur pos terpilih = LEVEL
HILIR_FILL = "rgba(29,95,191,0.13)"  # kecamatan di hilir pos terpilih


def _bundled(name):
    return json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))


# Kota (DKI + Depok/Tangerang/Tangsel sebagai konteks), kecamatan DKI, alur sungai tiap pos (plus alur
# hulu dari titik pos, properti `pos`) dan kelurahan di hilirnya: OpenStreetMap (ODbL), dibangun oleh
# build_wilayah.py (`make wilayah`). Hilir = perkiraan dari alur sungai + buffer, bukan daftar resmi BPBD.
REGIONS = _bundled("kota.geojson")
KECAMATAN = _bundled("kecamatan.geojson")
SUNGAI = _bundled("sungai.geojson")
_hilir = _bundled("hilir.json")
HILIR = _hilir["pos"]  # {pos: {sungai, sampai, kelurahan: [[kelurahan, kecamatan, kota]]}}
HILIR_BUFFER_M = _hilir["buffer_m"]
DKI_FILL = "#e3e7ed"  # satu nada netral untuk DKI, wilayah konteks lebih pucat: warna di peta hanya status pos
REGION_FILL = {"Depok": "#eef0f3", "Tangerang": "#eef0f3", "Tangerang Selatan": "#eef0f3"}
REGION_LABEL_AT = {  # titik label yang tidak menabrak label pos
    "Jakarta Utara": (106.905, -6.118), "Jakarta Barat": (106.713, -6.135), "Jakarta Pusat": (106.838, -6.172),
    "Jakarta Selatan": (106.80, -6.30), "Jakarta Timur": (106.925, -6.28), "Depok": (106.91, -6.40),
    "Tangerang": (106.69, -6.165), "Tangerang Selatan": (106.705, -6.29),
}

SIAGA_NAME = {4: "Normal", 3: "Waspada", 2: "Siaga", 1: "Awas"}
SIAGA_COLOR = {4: "#3d3d3d", 3: "#d49a00", 2: "#d9620f", 1: "#c4242a"}  # titik di peta; normal = tinta
NO_STATUS = "#9a9c9e"  # pos tanpa ambang siaga
BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def siaga_level(cm, limits):
    """Status siaga (4 normal ... 1 awas) dari TMA; `limits` = {3: cm, 2: cm, 1: cm}, TMA harus > batas.

    Strict `>` karena API sisteminformasibanjir memberi status lebih rendah tepat di angka batas
    tabel SOP BPBD (config/dashboard.yaml). None kalau TMA atau ambangnya tidak ada.
    """
    if cm is None or not limits:
        return None
    for level in (1, 2, 3):
        if level in limits and cm > limits[level]:
            return level
    return 4


def hilir_kecamatan(station, hilir=None):
    """{kecamatan: [kelurahan]} di hilir pos, urut hulu ke hilir; {} kalau pos tidak ada di hilir.json."""
    hilir = HILIR if hilir is None else hilir
    out = {}
    for kelurahan, kecamatan, _ in (hilir.get(station) or {}).get("kelurahan", []):
        out.setdefault(kecamatan, []).append(kelurahan)
    return out


def station_rows(levels, forecast, coords, rise_cm=10.0):
    """Satu dict per stasiun: TMA aktual terakhir, prediksi per horizon, puncaknya dan apakah naik.

    Stasiun = yang ada di forecast, plus yang punya koordinat dan kolom di `levels` (tanpa
    forecast tetap tampil di peta), dalam urutan `coords` (config: per aliran, hulu ke hilir).
    `change` = puncak forecast - TMA aktual, dari dua angka yang ditampilkan; `rising` kalau
    change >= rise_cm. `status_by_h` = status siaga per horizon, kunci 0 = TMA sekarang.
    """
    names = set(forecast["station"]) if not forecast.empty else set()
    names |= set(levels.columns) & set(coords)
    rows = []
    for name in [n for n in coords if n in names] + sorted(names - set(coords)):
        series = levels[name].dropna() if name in levels.columns else pd.Series(dtype=float)
        now = round(float(series.iloc[-1]), 1) if len(series) else None
        by_h = {}
        if not forecast.empty:
            sub = forecast[forecast["station"] == name].set_index("horizon")["predicted_value_cm"]
            by_h = {int(h): round(float(v), 1) for h, v in sub.items()}
        peak_h = max(by_h, key=by_h.get) if by_h else None
        peak = by_h[peak_h] if by_h else None
        change = round(peak - now, 1) if peak is not None and now is not None else None
        rising_by_h = {h: round(v - now, 1) >= rise_cm for h, v in by_h.items()} if now is not None else {}
        meta = coords.get(name, {})
        limits = meta.get("siaga") or {}
        status_by_h = {h: siaga_level(v, limits) for h, v in {0: now, **by_h}.items()}
        rows.append({
            "station": name, "label": meta.get("label", name), "side": meta.get("side", "right"),
            "aliran": meta.get("aliran"), "lat": meta.get("lat"), "lon": meta.get("lon"), "limits": limits,
            "now": now, "forecasts": by_h, "peak": peak, "peak_h": peak_h, "change": change,
            "rising": change is not None and change >= rise_cm, "rising_by_h": rising_by_h,
            "status_by_h": {h: s for h, s in status_by_h.items() if s is not None},
        })
    return rows


def gauge(row):
    """Papan duga mini satu pos: posisi TMA sekarang dan puncak prakiraan terhadap batas siaganya.

    Skala per pos, dari yang terendah (TMA, prakiraan, batas Siaga 3) sampai yang tertinggi (TMA,
    prakiraan, batas Siaga 1), jadi semua batas selalu terlihat dan jarak ke bahaya terbaca jujur.
    Return {"zones": [(status, x0, x1)], "now": x, "peak": x} dalam persen lebar; None tanpa ambang atau angka.
    """
    limits = row["limits"]
    values = [v for v in (row["now"], *row["forecasts"].values()) if v is not None]
    cuts = [(lvl, limits[lvl]) for lvl in (3, 2, 1) if lvl in limits]
    if not cuts or not values:
        return None
    lo, hi = min(values + [cuts[0][1]]), max(values + [cuts[-1][1]])
    pad = 0.08 * ((hi - lo) or 1.0)
    lo, hi = lo - pad, hi + pad

    def pct(v):
        return round(100 * (v - lo) / (hi - lo), 2)

    starts = [(4, 0.0)] + [(lvl, pct(cm)) for lvl, cm in cuts]
    zones = [(lvl, x0, starts[i + 1][1] if i + 1 < len(starts) else 100.0) for i, (lvl, x0) in enumerate(starts)]
    return {"zones": zones, "now": pct(row["now"]) if row["now"] is not None else None,
            "peak": pct(row["peak"]) if row["peak"] is not None else None}


def rain_cell_coords(column):
    """'rain_s6_8541_e106_9082' -> (-6.8541, 106.9082); None kalau bukan kolom sel hujan."""
    m = re.fullmatch(r"rain_([ns])(\d+)_(\d+)_([ew])(\d+)_(\d+)", column)
    if not m:
        return None
    lat = float(f"{m[2]}.{m[3]}") * (-1 if m[1] == "s" else 1)
    lon = float(f"{m[5]}.{m[6]}") * (-1 if m[4] == "w" else 1)
    return lat, lon


def rain_totals(rain, steps=24):
    """Jumlah hujan per sel (mm) selama `steps` langkah terakhir; Series kosong kalau tak ada data."""
    if rain is None or rain.empty:
        return pd.Series(dtype=float)
    cols = [c for c in rain.columns if rain_cell_coords(c)]
    return rain[cols].tail(steps).sum().round(1)


def station_rain(rain, cells):
    """Hujan per jam (mm) rata-rata sel yang dipakai model untuk satu pos; None kalau tak ada."""
    cols = [c for c in (cells or []) if rain is not None and c in rain.columns]
    return rain[cols].mean(axis=1).round(2) if cols else None


def map_figure(rows, selected, unit="jam", horizon=None, regions=None, kecamatan=None, sungai=None, hilir=None):
    """Peta wilayah Jakarta (lima kota, plus Depok dan Tangerang yang lebih pucat) digambar sederhana, tanpa
    tile, dengan satu titik per pos.

    Di dalam DKI: garis kecamatan tipis dan alur sungai tiap pos; dari pos hulu di luar DKI ada alur
    putus-putus sampai sungainya. Alur pos terpilih ditebalkan dan kecamatan di hilirnya diarsir;
    arahkan kursor ke arsiran untuk daftar kelurahannya (hilir.json).
    Warna titik = status siaga pos pada `horizon` (0 = TMA sekarang); tinta untuk Normal, abu-abu kalau
    ambangnya belum ada. Pos di luar wilayah yang digambar (Katulampa di Bogor) ditaruh di tepi bawah
    dengan panah dan jaraknya. Pos terpilih diberi cincin. `customdata` = nama stasiun supaya klik di
    peta memilih pos.
    """
    regions = REGIONS if regions is None else regions
    kecamatan = KECAMATAN if kecamatan is None else kecamatan
    sungai = SUNGAI if sungai is None else sungai
    hilir = HILIR if hilir is None else hilir
    fig = go.Figure()
    x0, x1, y0, y1 = _bounds(regions)
    for feature in regions["features"]:
        name = feature["properties"]["name"]
        xs, ys = _rings(feature)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor=REGION_FILL.get(name, DKI_FILL),
                                 line={"color": "#ffffff", "width": 2}, hoverinfo="skip", showlegend=False,
                                 name=name))
        lx, ly = REGION_LABEL_AT.get(name) or _centre(xs, ys)
        fig.add_annotation(x=lx, y=ly, text=name, showarrow=False, font={"size": 12, "color": "#5b6168"})

    downstream = hilir_kecamatan(selected, hilir)
    for feature in kecamatan["features"]:
        name = feature["properties"]["name"]
        if name in downstream:
            xs, ys = _rings(feature)
            # teks skalar: plotly memakainya sebagai label hover arsiran (hoveron="fills")
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor=HILIR_FILL,
                                     line={"width": 0}, hoveron="fills", hoverinfo="text",
                                     text=f"<b>Kec. {name}</b>, hilir {selected}<br>{_wrap(downstream[name])}",
                                     showlegend=False, name=f"Hilir {name}"))
    xs, ys = [], []
    for feature in kecamatan["features"]:
        fx, fy = _rings(feature)
        xs, ys = xs + fx, ys + fy
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line={"color": "#ffffff", "width": 0.8},
                                 hoverinfo="skip", showlegend=False, name="Kecamatan"))
    river = (hilir.get(selected) or {}).get("sungai")
    for feature in sorted(sungai["features"], key=lambda f: f["properties"]["name"] == river):
        on, pos = feature["properties"]["name"] == river, feature["properties"].get("pos")
        xs, ys = _lines(feature)
        # alur hulu (dari titik pos ke sungai di DKI) putus-putus: diturunkan dari jaringan sungai OSM
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                 line={"color": LEVEL if on else RIVER, "width": 2 if on else 1,
                                       "dash": "dot" if pos else "solid"}, hoverinfo="skip", showlegend=False,
                                 name=f"Hulu {pos}" if pos else f"Sungai {feature['properties']['name']}"))

    placed = []
    for r in rows:
        if r["lat"] is None:
            continue
        lat, label, hover_note = r["lat"], r["label"], ""
        if lat < y0:  # di luar peta, di hulu: taruh di tepi bawah
            label = f"{r['label']} ↓ {round((y0 - lat) * 111):d} km"
            hover_note = "<br>di luar peta, arah selatan"
            lat = y0 - 0.012
        placed.append({**r, "plot_lat": lat, "plot_label": label, "hover_note": hover_note})

    chosen = [r for r in placed if r["station"] == selected]
    if chosen:
        fig.add_trace(go.Scatter(x=[r["lon"] for r in chosen], y=[r["plot_lat"] for r in chosen], mode="markers",
                                 marker={"size": 24, "color": "#ffffff", "line": {"color": INK, "width": 2}},
                                 hoverinfo="skip", showlegend=False, name="Terpilih"))

    for side in ("right", "left"):
        group = [r for r in placed if r["side"] == side]
        if not group:
            continue
        fig.add_trace(go.Scatter(
            x=[r["lon"] for r in group], y=[r["plot_lat"] for r in group], mode="markers+text",
            marker={"size": 13, "color": [SIAGA_COLOR.get(r["status_by_h"].get(horizon), NO_STATUS) for r in group],
                    "line": {"color": "#ffffff", "width": 2}},
            text=[_label(r["plot_label"], side) for r in group], textposition=f"middle {side}",
            textfont={"size": 12, "color": INK, "family": FONT},
            customdata=[r["station"] for r in group],
            hovertext=[_hover(r, unit, horizon) + r["hover_note"] for r in group],
            hovertemplate="%{hovertext}<extra></extra>", showlegend=False, name="Pos", cliponaxis=False))

    pad = 0.012
    fig.update_layout(
        margin={"l": 8, "r": 8, "t": 8, "b": 8}, dragmode=False, clickmode="event",
        font={"family": FONT, "color": INK}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False, "range": [x0 - pad, x1 + pad], "fixedrange": True},
        # 1 derajat bujur di lintang Jakarta = cos(6.3 derajat) derajat lintang
        yaxis={"visible": False, "range": [y0 - 0.03, y1 + pad], "fixedrange": True,
               "scaleanchor": "x", "scaleratio": 1.006},
        hoverlabel={"bgcolor": "#ffffff", "font": {"family": FONT, "size": 13, "color": INK},
                    "bordercolor": GRID},
    )
    return fig


def _rings(feature):
    """Semua ring luar fitur sebagai satu deret x/y dipisah None (satu trace per wilayah)."""
    xs, ys = [], []
    for polygon in feature["geometry"]["coordinates"]:
        ring = polygon[0]
        xs += [x for x, _ in ring] + [None]
        ys += [y for _, y in ring] + [None]
    return xs, ys


def _lines(feature):
    """Garis (Multi)LineString sebagai satu deret x/y dipisah None."""
    geometry = feature["geometry"]
    parts = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
    xs, ys = [], []
    for part in parts:
        xs += [x for x, _ in part] + [None]
        ys += [y for _, y in part] + [None]
    return xs, ys


def _wrap(names, per_line=4):
    """Daftar nama untuk label hover, beberapa per baris supaya kotak hover tidak selebar peta."""
    return "<br>".join(", ".join(names[i:i + per_line]) for i in range(0, len(names), per_line))


def _centre(xs, ys):
    points = [(x, y) for x, y in zip(xs, ys) if x is not None]
    return sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)


def _bounds(regions):
    xs = [x for f in regions["features"] for p in f["geometry"]["coordinates"] for x, _ in p[0]]
    ys = [y for f in regions["features"] for p in f["geometry"]["coordinates"] for _, y in p[0]]
    return min(xs), max(xs), min(ys), max(ys)


def _label(text, side):
    """Spasi tipis supaya cincin pos terpilih tidak menimpa huruf pertama."""
    return f" {text}" if side == "right" else f"{text} "


def _fmt(value, decimals=1):
    return "–" if value is None else f"{value:.{decimals}f}"


def _hover(row, unit, horizon=None):
    text = f"<b>{row['station']}</b><br>TMA {_fmt(row['now'])} cm{_status_suffix(row, 0)}"
    value = row["forecasts"].get(horizon)
    if value is not None:
        text += f"<br>+{horizon} {unit}: {_fmt(value)} cm{_status_suffix(row, horizon)}"
        if row["now"] is not None:
            text += f" ({round(value - row['now'], 1):+.1f})"
    return text


def _status_suffix(row, horizon):
    level = row["status_by_h"].get(horizon)
    return "" if level is None else f" · Siaga {level}"


def station_figure(levels, forecast, station, unit="jam", limits=None):
    """TMA aktual sebagai area halus + prakiraan titik-titik yang disambung dari titik "sekarang".

    Batas siaga (`limits` = {3: cm, 2: cm, 1: cm}) hanya ditandai kecil di sisi kanan, dan hanya yang
    dekat dengan data; batas yang jauh di atas tidak ditandai supaya garis TMA tidak gepeng (jaraknya
    ada di kartu detail). Garis aktual dihaluskan (spline) supaya tangga 10 cm sensor tidak terlihat kaku.
    """
    limits = limits or {}
    fig = go.Figure()
    actual = levels[station].dropna() if station in levels.columns else pd.Series(dtype=float)
    fc = forecast[forecast["station"] == station].sort_values("forecast_time")
    bottom, top, marks = _y_frame(actual, fc, limits)

    if len(actual):
        # garis dasar tak terlihat di dasar sumbu: isian area berhenti di sana, bukan di nol (Pluit negatif)
        fig.add_trace(go.Scatter(x=actual.index, y=[bottom] * len(actual), mode="lines", line={"width": 0},
                                 hoverinfo="skip", showlegend=False, name="Dasar"))
        fig.add_trace(go.Scatter(x=actual.index, y=actual, mode="lines", name="Aktual", fill="tonexty",
                                 fillcolor="rgba(29,95,191,0.10)",
                                 line={"color": LEVEL, "width": 2.5, "shape": "spline", "smoothing": 0.6},
                                 hovertemplate="TMA %{y:.1f} cm<extra></extra>"))

    x_end = actual.index.max() if len(actual) else None
    if not fc.empty:
        x, y = list(fc["forecast_time"]), list(fc["predicted_value_cm"])
        hover = [f"+{h} {unit}" for h in fc["horizon"]]
        colours = [SIAGA_COLOR[s] if (s := siaga_level(v, limits)) in (1, 2, 3) else LEVEL for v in y]
        sizes = [8] * (len(y) - 1) + [10]
        texts = [""] * (len(y) - 1) + [f"{hover[-1]} · {y[-1]:.1f} cm"]
        as_of = fc["as_of"].iloc[0]
        before = actual.loc[:as_of]
        if not before.empty:
            x, y, hover = [before.index[-1]] + x, [before.iloc[-1]] + y, ["Sekarang"] + hover
            colours, sizes, texts = [LEVEL] + colours, [10] + sizes, [""] + texts
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines+markers+text", name="Prakiraan",
                                 line={"color": LEVEL, "dash": "dot", "width": 2.5},
                                 marker={"size": sizes, "color": colours, "line": {"color": "#ffffff", "width": 2}},
                                 text=texts, textposition="top left", textfont={"size": 13, "color": INK},
                                 customdata=hover, hovertemplate="%{customdata}: %{y:.1f} cm<extra></extra>",
                                 cliponaxis=False))
        x_end = fc["forecast_time"].max()
        fig.add_shape(type="line", xref="x", yref="paper", x0=as_of.to_pydatetime(), x1=as_of.to_pydatetime(),
                      y0=0, y1=1, line={"color": "#cfd3d8", "width": 1, "dash": "dot"}, layer="below")
        fig.add_annotation(x=as_of.to_pydatetime(), xref="x", yref="paper", y=0, text="Sekarang",
                           showarrow=False, xanchor="right", xshift=-6, yanchor="bottom", yshift=6,
                           font={"size": 13, "color": MUTED})

    for cm, lvl in marks:
        fig.add_shape(type="line", xref="paper", yref="y", x0=1.0, x1=1.025, y0=cm, y1=cm,
                      line={"color": SIAGA_COLOR[lvl], "width": 3})
        fig.add_annotation(xref="paper", yref="y", x=1.03, y=cm, text=f"Siaga {lvl} · {cm:g}", showarrow=False,
                           xanchor="left", yanchor="middle", font={"size": 12, "color": MUTED})

    if len(actual):
        ticks = _time_ticks(actual.index.min(), x_end, hourly=unit == "jam")
        fig.update_xaxes(tickmode="array", tickvals=[t for t, _ in ticks], ticktext=[label for _, label in ticks],
                         showgrid=False, showline=False, zeroline=False, tickangle=0)

    fig.update_layout(
        margin={"l": 44, "r": 108 if marks else 16, "t": 12, "b": 28}, hovermode="x unified",
        font={"family": FONT, "size": 13, "color": MUTED}, plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
        yaxis={"gridcolor": "#f0f1f3", "zeroline": False, "showline": False, "nticks": 5,
               **({"range": [bottom, top]} if len(actual) else {})},
        hoverlabel={"bgcolor": "#ffffff", "font": {"family": FONT, "size": 13, "color": INK},
                    "bordercolor": GRID},
    )
    return fig


def _time_ticks(start, end, hourly):
    """Tanda sumbu waktu berbahasa Indonesia: tengah malam diberi tanggal, jam lain hanya jamnya."""
    span = end - start
    if hourly:
        step = "6h" if span <= pd.Timedelta(hours=36) else "24h"
        stamps = pd.date_range(start.ceil(step), end, freq=step)
        return [(t, _day_label(t) if t.hour == 0 else f"{t.hour:02d}:00") for t in stamps]
    step = "D" if span <= pd.Timedelta(days=10) else "7D"
    return [(t, _day_label(t)) for t in pd.date_range(start.ceil("D"), end, freq=step)]


def _day_label(ts):
    return f"{ts.day} {BULAN[ts.month - 1]}"


def _y_frame(actual, fc, limits):
    """(bawah, atas, tanda) sumbu y: data + batas siaga yang dekat; tanda = [(cm, status)] urut naik.

    Batas dekat di bawah data (pos yang seharian di atas suatu batas, atau batas negatif Pluit) ikut
    memperlebar dasar sumbu, supaya tandanya tidak tergambar di luar plot, di atas label waktu.
    """
    ys = list(actual) + (list(fc["predicted_value_cm"]) if not fc.empty else [])
    if not ys:
        return 0.0, 1.0, []
    lo, hi = min(ys), max(ys)
    # rentang minimum 60 cm: sensor melangkah per 10 cm, jadi goyangan beberapa cm tidak tampak seperti lonjakan
    span = max(hi - lo, 60.0)
    marks = sorted((cm, lvl) for lvl, cm in limits.items() if lo - 0.6 * span <= cm <= hi + 0.6 * span)
    bottom = min([lo] + [cm for cm, _ in marks])
    top = max([hi] + [cm for cm, _ in marks])
    if top - bottom < 60.0:  # data datar: taruh di tengah rentang 60 cm
        mid = (top + bottom) / 2
        bottom, top = mid - 30.0, mid + 30.0
    reach = top - bottom
    return bottom - 0.15 * reach, top + 0.12 * reach, marks
