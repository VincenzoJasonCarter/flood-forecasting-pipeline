"""Laporan unduhan sebagai PDF A4 (ReportLab, murni Python): isi dari `report.report_content`, rupa dari dashboard.

Bahasa visualnya sama dengan dashboard: Geist (dibundel di fonts/, SIL OFL), tinta dan abu-abu untuk teks,
warna hanya untuk status siaga, dan papan duga mini per pos (zona siaga, TMA sekarang, puncak prakiraan biru).
"""

import math
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

import pandas as pd

from .figures import BULAN, SIAGA_NAME, _y_frame, gauge, siaga_level
from .overview import num_id, rain_band
from .report_sections import join

_FONT_DIR = Path(__file__).with_name("fonts")
for _weight in ("Regular", "Medium", "Bold"):
    pdfmetrics.registerFont(TTFont(f"Geist-{_weight}", str(_FONT_DIR / f"Geist-{_weight}.ttf")))
pdfmetrics.registerFontFamily("Geist", normal="Geist-Regular", bold="Geist-Bold",
                              italic="Geist-Regular", boldItalic="Geist-Bold")

# token dashboard.css
INK, MUTED, RULE, SOFT_RULE = "#0a0a0a", "#6b6b6b", "#e6e6e6", "#f0f0f0"
RAISED, LEVEL, NO_STATUS = "#f2f4f7", "#1d5fbf", "#9a9c9e"
STATUS = {4: "#1d4f9f", 3: "#f2b01e", 2: "#ee7a4c", 1: "#d6303a"}
CELL_BG = {4: "#dfe9f8", 3: "#fdf0c4", 2: "#fde4d8", 1: "#fbdcdc"}
CELL_INK = {4: "#1d4f9f", 3: "#7a4a00", 2: "#9a3412", 1: "#831c1e"}
BLUE_INK, BLUE_BG = "#1d4f9f", "#eef2fb"
BANNER = {("alert", 3): ("#fff7de", "#f0dc9c"), ("alert", 2): ("#fdeee8", "#f3c3ad"), ("alert", 1): ("#fdeceb", "#f0b4b2"),
          ("safe", 4): ("#eef2fb", "#c9d8f1")}
ICON = {3: "#d99a0a", 2: "#c8541a", 1: "#b8232c", 4: "#1d4f9f"}
RAIN_RAMP = ("#dbe6f5", "#aac4e6", "#6f9bd2", "#3f74b8", "#1f4a8c")
ZONE = {4: "#e3e7ed", 3: "#f9ebc0", 2: "#f8d9c2", 1: "#f3c9c6"}

PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 18 * mm, 24 * mm, 22 * mm
WIDTH = PAGE_W - 2 * MARGIN_X


def _style(name, size, leading, font="Geist-Regular", color=INK, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=colors.HexColor(color), **kw)


S = {
    "h1": _style("h1", 22, 28, "Geist-Bold"),
    "eyebrow": _style("eyebrow", 7.5, 10, "Geist-Bold"),
    "banner_h": _style("banner_h", 17, 21, "Geist-Bold", spaceBefore=3, spaceAfter=4),
    "banner_p": _style("banner_p", 9.5, 14),
    "kc_num": _style("kc_num", 22, 26, "Geist-Bold", spaceBefore=2, spaceAfter=4),
    "big": _style("big", 20, 24, "Geist-Bold", color=BLUE_INK, spaceBefore=6),
    "big_line": _style("big_line", 8.5, 12),
    "meta": _style("meta", 8.5, 12, color=MUTED, spaceBefore=4),
    "h2": _style("h2", 14, 19, "Geist-Bold", spaceBefore=16, keepWithNext=1),
    "hint": _style("hint", 8.5, 12, color=MUTED, spaceBefore=2, spaceAfter=10, keepWithNext=1),
    "label": _style("label", 8, 11, color=MUTED),
    "status": _style("status", 20, 24, "Geist-Medium", spaceBefore=3, spaceAfter=2),
    "finding": _style("finding", 12, 17, "Geist-Medium"),
    "body": _style("body", 9.5, 14),
    "body_j": _style("body_j", 9.5, 14.5, alignment=TA_JUSTIFY, spaceBefore=5),
    "h3": _style("h3", 10.5, 14, "Geist-Bold", spaceBefore=12, spaceAfter=1, keepWithNext=1),
    "figcap": _style("figcap", 8, 11, color=MUTED, spaceBefore=4, spaceAfter=6),
    "tabcap": _style("tabcap", 8, 11, color=MUTED, spaceBefore=10, spaceAfter=4, keepWithNext=1),
    "numbered": _style("numbered", 9.5, 14, leftIndent=14, bulletIndent=0, spaceBefore=4, alignment=TA_JUSTIFY),
    "bullet": _style("bullet", 9.5, 14, leftIndent=10, bulletIndent=0, spaceBefore=3),
    "name": _style("name", 11.5, 15, "Geist-Medium"),
    "chips": _style("chips", 8.5, 12, alignment=TA_RIGHT),
    "caption": _style("caption", 8, 11, color=MUTED, spaceBefore=3),
    "act": _style("act", 9, 13),
    "areas": _style("areas", 8, 11.5, color=MUTED, spaceBefore=2),
    "th": _style("th", 7.5, 10, color=MUTED),
    "th_r": _style("th_r", 7.5, 10, color=MUTED, alignment=TA_RIGHT),
    "td": _style("td", 8.5, 11),
    "td_r": _style("td_r", 8.5, 11, alignment=TA_RIGHT),
    "group": _style("group", 8, 11, color=MUTED),
    "note": _style("note", 8.5, 12.5, leftIndent=10, bulletIndent=0, spaceBefore=3),
    "footer": _style("footer", 7, 9.5, color=MUTED),
}


def _t(text):
    return escape(str(text))


def _dot(level, size=None):
    colour = STATUS.get(level, NO_STATUS)
    return f'<font color="{colour}"{f" size={size}" if size else ""}>●</font>'


def _status_word(level):
    return "Tanpa ambang" if level is None else SIAGA_NAME[4] if level == 4 else f"Siaga {level}"


def _fmt(value):
    return "–" if value is None else num_id(value).replace("-", "−")


class GaugeBar(Flowable):
    """Papan duga mini: zona siaga pos (skala per pos, figures.gauge), garis biru ke puncak, tanda tinta TMA."""

    def __init__(self, row, width, height=12):
        super().__init__()
        self.g, self.width, self.height = gauge(row), width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c, g = self.canv, self.g
        if g is None:
            return
        w, mid, th = self.width, self.height / 2, 5.0
        x = lambda pct: w * pct / 100  # noqa: E731
        c.saveState()
        track = c.beginPath()
        track.roundRect(0, mid - th / 2, w, th, th / 2)
        c.clipPath(track, stroke=0, fill=0)
        for level, x0, x1 in g["zones"]:
            c.setFillColor(colors.HexColor(ZONE[level]))
            c.rect(x(x0), mid - th / 2, x(x1) - x(x0), th, stroke=0, fill=1)
        c.restoreState()
        now, peak = g["now"], g["peak"]
        if now is not None and peak is not None:
            a, b = sorted((x(now), x(peak)))
            c.setFillColor(colors.HexColor(LEVEL))
            c.rect(a, mid - 1.2, b - a, 2.4, stroke=0, fill=1)
        if peak is not None:
            c.setFillColor(colors.white)
            c.circle(x(peak), mid, 3.8, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(LEVEL))
            c.circle(x(peak), mid, 2.7, stroke=0, fill=1)
        if now is not None:
            c.setFillColor(colors.white)
            c.roundRect(x(now) - 1.9, mid - 5.6, 3.8, 11.2, 1.2, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(INK))
            c.roundRect(x(now) - 1.0, mid - 5.0, 2.0, 10.0, 0.8, stroke=0, fill=1)


def _mark(c, x, y, size, fill=INK, wave="#ffffff"):
    """Logo dashboard (assets/mark.svg): lingkaran tinta dengan dua gelombang putih; (x, y) = kiri bawah.
    `fill`/`wave` dibalik untuk latar gelap (sampul pita)."""
    s = size / 24
    c.setFillColor(colors.HexColor(fill))
    c.circle(x + 12 * s, y + 12 * s, 12 * s, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor(wave))
    c.setLineWidth(1.8 * s)
    c.setLineCap(1)
    for dy in (0, 4.5):
        X, Y = (lambda u: x + u * s), (lambda v: y + (24 - v - dy) * s)  # noqa: E731
        p = c.beginPath()
        p.moveTo(X(4.5), Y(10))
        p.curveTo(X(6.9), Y(7.6), X(9.3), Y(7.6), X(12), Y(10))
        p.curveTo(X(14.7), Y(12.4), X(17.1), Y(12.4), X(19.5), Y(10))
        c.drawPath(p, stroke=1, fill=0)


def _canvas_class(doc):
    """Canvas yang menggambar kepala dan kaki tiap halaman setelah jumlah halaman diketahui."""

    class _Canvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._states = []

        def showPage(self):
            self._states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            # halaman 1 = sampul: tanpa kepala/kaki dan tidak dihitung; nomor halaman mulai dari naskah
            for number, state in enumerate(self._states, 1):
                self.__dict__.update(state)
                if number > 1:
                    self._chrome(number - 1, len(self._states) - 1)
                super().showPage()
            super().save()

        def _chrome(self, number, total):
            top = PAGE_H - 13 * mm
            _mark(self, MARGIN_X, top - 1, 11)
            self.setFont("Geist-Medium", 8.5)
            self.setFillColor(colors.HexColor(INK))
            self.drawString(MARGIN_X + 16, top + 2, "Flood Forecast")
            self.setFont("Geist-Regular", 8.5)
            self.setFillColor(colors.HexColor(MUTED))
            self.drawString(MARGIN_X + 16 + pdfmetrics.stringWidth("Flood Forecast ", "Geist-Medium", 8.5), top + 2,
                            "· Jakarta")
            self.drawRightString(PAGE_W - MARGIN_X, top + 2, f"Laporan banjir · {doc['stamp']} WIB")
            self.setStrokeColor(colors.HexColor(RULE))
            self.setLineWidth(0.6)
            self.line(MARGIN_X, PAGE_H - 17 * mm, PAGE_W - MARGIN_X, PAGE_H - 17 * mm)
            self.line(MARGIN_X, 15 * mm, PAGE_W - MARGIN_X, 15 * mm)
            sources = Paragraph(_t(doc["sources"]), S["footer"])
            _, h = sources.wrap(WIDTH - 70, 30)
            sources.drawOn(self, MARGIN_X, 15 * mm - 4 - h)
            self.setFont("Geist-Regular", 7.5)
            self.drawRightString(PAGE_W - MARGIN_X, 15 * mm - 11, f"Halaman {number} dari {total}")

    return _Canvas


class WorstStrip(Flowable):
    """Kolom kanan banner: status terparah sekarang dan di tiap horizon (bar berwarna, nama status, jumlah pos)."""

    def __init__(self, banner, width):
        super().__init__()
        self.b, self.width, self.height = banner, width, 66

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c, cols = self.canv, self.b["worst"]
        c.setFont("Geist-Bold", 8)
        c.setFillColor(colors.HexColor(INK))
        c.drawString(0, self.height - 8, self.b["worst_title"])
        gap = 14
        w = (self.width - gap * (len(cols) - 1)) / len(cols)
        for i, col in enumerate(cols):
            x, level = i * (w + gap), col["level"]
            c.setFont("Geist-Bold", 7.5)
            c.setFillColor(colors.HexColor(INK))
            c.drawString(x, self.height - 24, col["label"])
            c.setFillColor(colors.HexColor(STATUS.get(level, NO_STATUS)))
            c.roundRect(x, self.height - 33, w, 5, 2.5, stroke=0, fill=1)
            c.setFont("Geist-Bold", 11)
            c.setFillColor(colors.HexColor(CELL_INK.get(level, MUTED)))
            c.drawString(x, self.height - 46, SIAGA_NAME[level] if level else "–")
            c.setFont("Geist-Regular", 6.8)
            c.setFillColor(colors.HexColor(MUTED))
            c.drawString(x, self.height - 57,
                         f"{col['above']} pos di atas Normal" if col["above"] else f"{col['graded']}/{col['graded']} pos Normal")


class StatusIcon(Flowable):
    """Lingkaran status dengan tanda seru (peringatan) atau centang (aman)."""

    def __init__(self, level, ok, size=30):
        super().__init__()
        self.level, self.ok, self.size = level, ok, size

    def wrap(self, *_):
        return self.size, self.size

    def draw(self):
        c, r = self.canv, self.size / 2
        c.setFillColor(colors.HexColor(ICON.get(self.level, NO_STATUS)))
        c.circle(r, r, r, stroke=0, fill=1)
        c.setStrokeColor(colors.white)
        c.setFillColor(colors.white)
        c.setLineWidth(2.4)
        c.setLineCap(1)
        c.setLineJoin(1)
        if self.ok:
            p = c.beginPath()
            p.moveTo(r * 0.52, r * 1.02)
            p.lineTo(r * 0.88, r * 0.66)
            p.lineTo(r * 1.5, r * 1.36)
            c.drawPath(p, stroke=1, fill=0)
        else:
            c.line(r, r * 0.78, r, r * 1.52)
            c.circle(r, r * 0.5, 1.3, stroke=0, fill=1)


def _lead(doc):
    """Banner status seperti di dashboard: peringatan (warna menurut level) atau aman, dengan status terburuk per waktu."""
    b = doc["banner"]
    bg, line = BANNER.get((b["kind"], b["level"]), (RAISED, RULE))
    ink = CELL_INK.get(b["level"], INK)
    text = [Paragraph(_t(b["eyebrow"]), _style("eb", 7.5, 10, "Geist-Bold", color=ink)) if b["eyebrow"] else Spacer(1, 0),
            Paragraph(_t(b["head"]), S["banner_h"]), Paragraph(_t(b["text"]), S["banner_p"])]
    inner = WIDTH - 32
    head = Table([[StatusIcon(b["level"], b["kind"] == "safe"), text]], colWidths=[42, inner - 42])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("LEFTPADDING", (1, 0), (1, 0), 10)]))
    rows = [[head]] + ([[Spacer(1, 6)], [WorstStrip(b, inner)]] if b["kind"] != "unknown" else [])
    table = Table(rows, colWidths=[WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)), ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(line)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 13), ("BOTTOMPADDING", (0, -1), (0, -1), 13),
    ]))
    return table


class MiniBar(Flowable):
    """Bar kecil kartu angka: segmen status per pos, skala hujan lima ruas dengan penanda, atau isian NSE 0-1."""

    def __init__(self, kind, width, data):
        super().__init__()
        self.kind, self.width, self.data, self.height = kind, width, data, 10

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c, w = self.canv, self.width
        if self.kind == "segments":
            n, gap = len(self.data), 3
            if not n:
                return
            seg = (w - gap * (n - 1)) / n
            for i, level in enumerate(self.data):
                c.setFillColor(colors.HexColor(STATUS.get(level, NO_STATUS)))
                c.roundRect(i * (seg + gap), 2, seg, 6, 1.5, stroke=0, fill=1)
        elif self.kind == "rain":
            seg = w / len(RAIN_RAMP)
            for i, colour in enumerate(RAIN_RAMP):
                c.setFillColor(colors.HexColor(colour))
                c.rect(i * seg, 2, seg, 6, stroke=0, fill=1)
            x = w * self.data / 100
            c.setFillColor(colors.white)
            c.roundRect(x - 2, 0, 4, 10, 1, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(INK))
            c.roundRect(x - 1.2, 0.5, 2.4, 9, 0.8, stroke=0, fill=1)
        else:
            c.setFillColor(colors.HexColor("#e8eaee"))
            c.roundRect(0, 2, w, 6, 3, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(LEVEL))
            c.roundRect(0, 2, max(w * min(max(self.data, 0), 1), 6), 6, 3, stroke=0, fill=1)


def _kpi_row(doc):
    """Tiga kotak angka seperti di dashboard: pos Normal, hujan 24 jam di DAS, keandalan model."""
    k, width = doc["kpis"], (WIDTH - 2 * 10) / 3
    inner = width - 28
    label = lambda text: Paragraph(_t(text), _style("kl", 8.5, 12, color="#3a3a3a"))  # noqa: E731
    sub = lambda text: Paragraph(_t(text), _style("ks", 8, 11, color="#3a3a3a", spaceBefore=5))  # noqa: E731
    unit = lambda text: f'<font name="Geist-Regular" size=9 color="{MUTED}"> {_t(text)}</font>'  # noqa: E731

    pos = [label("Pos Normal · sekarang"),
           Paragraph(f"{k['normal']}/{len(k['levels'])}{unit('pos')}", S["kc_num"]), MiniBar("segments", inner, k["levels"]),
           sub(", ".join(k["off"]) if 0 < len(k["off"]) <= 2 else f"{len(k['off'])} pos di atas Normal" if k["off"]
               else "Tidak ada pos Waspada, Siaga, atau Awas")]
    if k["rain_mean"] is not None:
        name, at = rain_band(k["rain_mean"])
        rain = [label("Hujan 24 jam di DAS"),
                Paragraph(f"{num_id(k['rain_mean'])}{unit('mm · ' + name)}", S["kc_num"]), MiniBar("rain", inner, at),
                sub(f"{k['rain_cells']} sel · terderas {num_id(k['rain_max'])} mm")]
    else:
        rain = [label("Hujan 24 jam di DAS"), Paragraph("–", S["kc_num"]), sub("Data hujan tidak terbaca")]
    value, metric, stat = k["stat_value"], k["metric"], k["stat"]
    if value is not None and metric == "NSE":
        model = [label("Keandalan model prakiraan"), Paragraph(f"{num_id(value, 2)}{unit('NSE ' + stat)}", S["kc_num"]),
                 MiniBar("fill", inner, value), sub(f"Model {k['model']} · 1 = sempurna")]
    elif value is not None:
        model = [label("Keandalan model prakiraan"), Paragraph(f"{num_id(value, 2)}{unit(metric + ' ' + stat)}", S["kc_num"]),
                 sub(f"Model {k['model']} · saat seleksi")]
    else:
        model = [label("Keandalan model prakiraan"), Paragraph("–", S["kc_num"]), sub(f"Model {k['model']}")]
    spaced = Table([[pos, "", rain, "", model]],
                   colWidths=[width, 10, width, 10, width])
    spaced.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 0.6, colors.HexColor(RULE)), ("BOX", (2, 0), (2, 0), 0.6, colors.HexColor(RULE)),
        ("BOX", (4, 0), (4, 0), 0.6, colors.HexColor(RULE)), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        *[(f"{side}PADDING", (c, 0), (c, 0), v) for c in (0, 2, 4) for side, v in
          (("LEFT", 14), ("RIGHT", 14), ("TOP", 9), ("BOTTOM", 9))],
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("LEFTPADDING", (3, 0), (3, 0), 0), ("RIGHTPADDING", (3, 0), (3, 0), 0),
    ]))
    return spaced


def _clock(ts):
    return f"{ts:%H:%M}"


def _hours(h):
    """Waktu tempuh, dibulatkan ke bawah seperti jam tibanya: '<1 jam', '~3 jam'."""
    return "<1 jam" if h < 1 else f"~{int(h)} jam"


def _clock_cell(ts, as_of, text=None):
    """Jam (atau `text` berisi jam) plus tanggal kecil kalau bukan tanggal data: '01:00 18 Nov'."""
    tag = "" if as_of is None or ts.normalize() == as_of.normalize() else f" {ts.day} {BULAN[ts.month - 1]}"
    return (text or _clock(ts)) + (f'<font size=7 color="{MUTED}">{tag}</font>' if tag else "")


def _nice_ticks(lo, hi, n=4):
    """Angka bulat untuk sumbu y: 0 / 50 / 100 ..."""
    raw = (hi - lo) / n if hi > lo else 1.0
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step) * step
    return [start + i * step for i in range(int((hi - start) // step) + 1)]


def _time_ticks(t0, t1, unit):
    """[(waktu, label)] sumbu x: jam bulat ('18:00'), tengah malam ditulis tanggalnya ('18 Nov')."""
    if unit == "jam":
        hours = (t1 - t0) / pd.Timedelta(hours=1)
        every = 6 if hours > 30 else 3 if hours > 12 else 2 if hours > 7 else 1
        stamps = pd.date_range(t0.ceil(f"{every}h"), t1, freq=f"{every}h")
        return [(t, f"{t.day} {BULAN[t.month - 1]}" if t.hour == 0 else f"{t:%H:%M}") for t in stamps]
    days = (t1 - t0).days
    return [(t, f"{t.day} {BULAN[t.month - 1]}") for t in pd.date_range(t0.ceil("D"), t1, freq="2D" if days > 10 else "D")]


def _axis_text(c, x, y, text, anchor="middle", size=6.5, color=MUTED, font="Geist-Regular"):
    c.setFont(font, size)
    c.setFillColor(colors.HexColor(color))
    {"middle": c.drawCentredString, "end": c.drawRightString, "start": c.drawString}[anchor](x, y, text)


class Hydrograph(Flowable):
    """Satu pos: hujan per langkah (batang, atas) dan TMA (bawah) berbagi sumbu waktu.

    TMA terukur = garis biru penuh dengan isian tipis; prakiraan = garis titik dari TMA terakhir ke tiap horizon,
    penandanya berwarna status siaga pada nilai itu. Pita = zona status siaga, label batasnya di kanan. Skala y
    per pos (dua pos tidak pernah berbagi sumbu); semua pos satu sungai memakai rentang waktu yang sama.
    """

    L, R, HEAD, RAIN, GAP, PLOT, AXIS = 34, 70, 15, 30, 12, 108, 13

    def __init__(self, chart, width, t0, t1):
        super().__init__()
        self.ch, self.width, self.t0, self.t1 = chart, width, t0, t1
        self.has_rain = any(v > 0 for _, v in chart["rain"])
        self.height = self.HEAD + (self.RAIN + self.GAP if self.has_rain else 10) + self.PLOT + self.AXIS

    def wrap(self, *_):
        return self.width, self.height

    def _x(self, t):
        pw = self.width - self.L - self.R
        return self.L + pw * ((t - self.t0) / (self.t1 - self.t0))

    def draw(self):
        c, ch = self.canv, self.ch
        pw = self.width - self.L - self.R
        right = self.L + pw
        top = self.height
        # kepala: titik status, nama pos, status sekarang dan terparah
        y = top - 9
        c.setFillColor(colors.HexColor(STATUS.get(ch["worst"], NO_STATUS)))
        c.circle(self.L - 8, y + 2.6, 3, stroke=0, fill=1)
        _axis_text(c, self.L, y, ch["label"], "start", 8.5, INK, "Geist-Bold")
        note = f"sekarang {_status_word(ch['level'])}"
        if ch["worst"] is not None and ch["worst"] < (ch["level"] or 4):
            note += f", diprakirakan {_status_word(ch['worst'])}"
        _axis_text(c, self.L + pdfmetrics.stringWidth(ch["label"], "Geist-Bold", 8.5) + 6, y, note, "start", 7.5)
        y = top - self.HEAD

        if self.has_rain:  # hujan: batang tipis, skala sendiri, angka maksimum di kiri
            rain = [(t, v) for t, v in ch["rain"] if self.t0 <= t <= self.t1]
            peak = max([v for _, v in rain] + [5.0])
            base = y - self.RAIN
            step = self._x(self.t0 + pd.Timedelta(1, "h" if ch["unit"] == "jam" else "D")) - self.L
            bar = max(min(step * 0.7, 6), 0.8)
            c.setFillColor(colors.HexColor(RAIN_RAMP[2]))
            for t, v in rain:
                if v > 0:
                    h = (self.RAIN - 4) * v / peak
                    c.roundRect(self._x(t) - bar / 2, base, bar, h, min(bar / 2, 1.5), stroke=0, fill=1)
            c.setStrokeColor(colors.HexColor(RULE))
            c.setLineWidth(0.5)
            c.line(self.L, base, right, base)
            _axis_text(c, self.L - 4, base + self.RAIN - 8, f"{num_id(peak, 0)} mm", "end")
            _axis_text(c, right + 4, base + 2, "hujan/jam" if ch["unit"] == "jam" else "hujan/hari", "start")
            y = base - self.GAP
        else:
            y -= 10

        plot_top, plot_bot = y, y - self.PLOT
        actual = pd.Series(dict(ch["actual"]), dtype=float)
        fc = pd.DataFrame({"predicted_value_cm": [v for _, v in ch["forecast"]]})
        lo, hi, marks = _y_frame(actual, fc, ch["limits"])
        yv = lambda v: plot_bot + self.PLOT * (v - lo) / (hi - lo)  # noqa: E731

        c.saveState()
        clip = c.beginPath()
        clip.rect(self.L, plot_bot, pw, self.PLOT)
        c.clipPath(clip, stroke=0, fill=0)
        cuts = sorted((cm, lvl) for lvl, cm in ch["limits"].items())
        for i, (cm, lvl) in enumerate(cuts):  # pita zona status: dari batasnya ke batas berikut
            upper = cuts[i + 1][0] if i + 1 < len(cuts) else hi
            c.setFillColor(colors.HexColor(ZONE[lvl]))
            c.rect(self.L, yv(cm), pw, yv(upper) - yv(cm), stroke=0, fill=1)
        as_of = ch["as_of"]
        if ch["forecast"] and as_of is not None:
            c.setFillColor(colors.HexColor(LEVEL))
            c.setFillAlpha(0.05)
            c.rect(self._x(as_of), plot_bot, right - self._x(as_of), self.PLOT, stroke=0, fill=1)
            c.setFillAlpha(1)
        c.setStrokeColor(colors.HexColor("#e3e5e8"))
        c.setLineWidth(0.4)
        ticks = _nice_ticks(lo, hi)
        for v in ticks:
            c.line(self.L, yv(v), right, yv(v))
        pts = [(self._x(t), yv(v)) for t, v in ch["actual"]]
        if len(pts) > 1:
            area = c.beginPath()
            area.moveTo(pts[0][0], plot_bot)
            for p in pts:
                area.lineTo(*p)
            area.lineTo(pts[-1][0], plot_bot)
            area.close()
            c.setFillColor(colors.HexColor(LEVEL))
            c.setFillAlpha(0.10)
            c.drawPath(area, stroke=0, fill=1)
            c.setFillAlpha(1)
            line = c.beginPath()
            line.moveTo(*pts[0])
            for p in pts[1:]:
                line.lineTo(*p)
            c.setStrokeColor(colors.HexColor(LEVEL))
            c.setLineWidth(1.5)
            c.setLineJoin(1)
            c.setLineCap(1)
            c.drawPath(line, stroke=1, fill=0)
        c.restoreState()

        if as_of is not None:  # garis "sekarang"; label di celah atas plot supaya tidak ditimpa data
            c.setStrokeColor(colors.HexColor("#9aa0a6"))
            c.setLineWidth(0.6)
            c.line(self._x(as_of), plot_bot, self._x(as_of), plot_top + 2)
            _axis_text(c, self._x(as_of) - 3, plot_top + 3, "Sekarang", "end")
            if ch["forecast"]:
                _axis_text(c, self._x(as_of) + 3, plot_top + 3, "Prakiraan →", "start")
        fpts = [(self._x(t), yv(v), v) for t, v in ch["forecast"]]
        if fpts:
            start = [pts[-1]] if pts else []
            chain = start + [(x, y) for x, y, _ in fpts]
            c.setStrokeColor(colors.HexColor(LEVEL))
            c.setLineWidth(1.5)
            c.setLineCap(1)
            c.setDash(0.1, 3)
            for a, b in zip(chain, chain[1:]):
                c.line(a[0], a[1], b[0], b[1])
            c.setDash()
            for x, y, v in fpts:
                lvl = siaga_level(v, ch["limits"])
                c.setFillColor(colors.white)
                c.circle(x, y, 4.2, stroke=0, fill=1)
                c.setFillColor(colors.HexColor(STATUS[lvl] if lvl in (1, 2, 3) else LEVEL))
                c.circle(x, y, 3, stroke=0, fill=1)
        # label hanya dua angka: puncak prakiraan dan TMA sekarang; yang kedua dibuang kalau bertabrakan
        peak_box = None
        if fpts:
            px, py, pv = max(fpts, key=lambda p: p[2])
            text = f"{num_id(pv)} cm"
            w = pdfmetrics.stringWidth(text, "Geist-Medium", 7)
            if py + 14 < plot_top:  # di atas titik; kalau mepet atas plot, di samping kanan (atau kiri di tepi)
                lx, ly, anchor, x0 = min(px, right - w / 2), py + 6, "middle", min(px, right - w / 2) - w / 2
            elif px + 7 + w < right:
                lx, ly, anchor, x0 = px + 7, py - 2.5, "start", px + 7
            else:
                lx, ly, anchor, x0 = px - 7, py - 2.5, "end", px - 7 - w
            _axis_text(c, lx, ly, text, anchor, 7, INK, "Geist-Medium")
            peak_box = (x0, ly, x0 + w, ly + 7)
        if pts:  # TMA sekarang: titik tinta di ujung garis terukur, angkanya sejajar di kiri (di atas garis yang naik)
            c.setFillColor(colors.white)
            c.circle(*pts[-1], 3.6, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(INK))
            c.circle(*pts[-1], 2.4, stroke=0, fill=1)
            text = f"{num_id(ch['actual'][-1][1])} cm"
            w = pdfmetrics.stringWidth(text, "Geist-Medium", 7)
            ax, ay = pts[-1][0] - 7, pts[-1][1] - 2.5
            box = (ax - w, ay, ax, ay + 7)
            clash = peak_box and not (box[2] + 3 < peak_box[0] or peak_box[2] + 3 < box[0]
                                      or box[3] + 2 < peak_box[1] or peak_box[3] + 2 < box[1])
            if not clash:
                _axis_text(c, ax, ay, text, "end", 7, INK, "Geist-Medium")

        for v in ticks:  # sumbu y kiri, batas siaga kanan
            _axis_text(c, self.L - 4, yv(v) - 2.2, num_id(v, 0).replace("-", "−"), "end")
        _axis_text(c, self.L - 4, plot_top + 2, "cm", "end")
        for cm, lvl in marks:
            if lo <= cm <= hi:
                c.setStrokeColor(colors.HexColor(STATUS[lvl]))
                c.setLineWidth(1.6)
                c.line(right, yv(cm), right + 5, yv(cm))
                _axis_text(c, right + 8, yv(cm) - 2.2, f"Siaga {lvl} · {cm:g}", "start")
        c.setStrokeColor(colors.HexColor(RULE))
        c.setLineWidth(0.6)
        c.line(self.L, plot_bot, right, plot_bot)
        for t, label in _time_ticks(self.t0, self.t1, ch["unit"]):
            _axis_text(c, self._x(t), plot_bot - 9, label)


class ArrivalTimeline(Flowable):
    """Kapan gelombang tiba di tiap kecamatan: satu baris per kecamatan, satu lajur per pos sumber.

    Titik = perkiraan tiba (warna = status gelombang di pos sumbernya); batang = jendela tindakan, dari tenggat
    SOP (garis tegak) sampai tiba. Tenggat yang sudah lewat dipotong di "sekarang". Angkanya ada di tabel.
    """

    L, R, LEGEND, AXIS = 112, 14, 16, 14

    def __init__(self, arr, width, unit):
        super().__init__()
        self.arr, self.width, self.unit = arr, width, unit
        self.lane_h = 7 if len(arr["lanes"]) > 1 else 0
        self.row_h = 15 + self.lane_h * (len(arr["lanes"]) - 1)
        as_of = arr["as_of"]
        times = [m["tiba"] for row in arr["rows"] for m in row["marks"].values() if m["tiba"] is not None]
        self.t0 = as_of - pd.Timedelta(hours=1)
        self.t1 = max(times + [as_of + pd.Timedelta(hours=3)]) + pd.Timedelta(hours=1)
        self.height = self.LEGEND + self.row_h * len(arr["rows"]) + self.AXIS

    def wrap(self, *_):
        return self.width, self.height

    def _x(self, t):
        return self.L + (self.width - self.L - self.R) * ((t - self.t0) / (self.t1 - self.t0))

    def draw(self):
        c, arr = self.canv, self.arr
        right, as_of = self.width - self.R, arr["as_of"]
        # legenda: satu entri per pos sumber, lalu kunci batang tenggat
        x, y = self.L, self.height - 9
        for lane in arr["lanes"]:
            c.setFillColor(colors.HexColor(STATUS.get(lane["level"], LEVEL)))
            c.circle(x + 3, y + 2.4, 3, stroke=0, fill=1)
            text = f"Tiba gelombang dari {lane['label']} ({_status_word(lane['level'])})"
            _axis_text(c, x + 9, y, text, "start", 7)
            x += 9 + pdfmetrics.stringWidth(text, "Geist-Regular", 7) + 14
        if any(m["tenggat"] for row in arr["rows"] for m in row["marks"].values()):
            c.setFillColor(colors.HexColor(NO_STATUS))
            c.setFillAlpha(0.45)
            c.roundRect(x, y + 0.8, 16, 3.4, 1.7, stroke=0, fill=1)
            c.setFillAlpha(1)
            c.setStrokeColor(colors.HexColor(NO_STATUS))
            c.setLineWidth(1.2)
            c.line(x, y - 1, x, y + 6)
            _axis_text(c, x + 21, y, "tenggat SOP → tiba", "start", 7)

        top = self.height - self.LEGEND
        bottom = top - self.row_h * len(arr["rows"])
        c.setStrokeColor(colors.HexColor("#e3e5e8"))
        c.setLineWidth(0.4)
        ticks = _time_ticks(self.t0, self.t1, self.unit)
        for t, _ in ticks:
            c.line(self._x(t), bottom, self._x(t), top)
        c.setStrokeColor(colors.HexColor("#9aa0a6"))
        c.setLineWidth(0.6)
        c.line(self._x(as_of), bottom, self._x(as_of), top + 2)
        _axis_text(c, self._x(as_of) + 3, top - 7, "Sekarang", "start")

        offsets = [((len(arr["lanes"]) - 1) / 2 - j) * self.lane_h for j in range(len(arr["lanes"]))]
        for i, row in enumerate(arr["rows"]):
            mid = top - self.row_h * (i + 0.5)
            _axis_text(c, 0, mid - 2.8, row["kecamatan"], "start", 8, INK)
            c.setStrokeColor(colors.HexColor(SOFT_RULE))
            c.setLineWidth(0.5)
            c.line(0, top - self.row_h * (i + 1), right, top - self.row_h * (i + 1))
            for lane, off in zip(arr["lanes"], offsets):
                m = row["marks"].get(lane["station"])
                if not m or m["tiba"] is None:
                    continue
                yy, colour = mid + off, STATUS.get(lane["level"], LEVEL)
                xt = self._x(m["tiba"])
                if m["tenggat"]:
                    xd = self._x(max(m["tenggat"]["at"], as_of))
                    c.setFillColor(colors.HexColor(colour))
                    c.setFillAlpha(0.35)
                    c.roundRect(xd, yy - 1.7, max(xt - xd, 0.1), 3.4, 1.7, stroke=0, fill=1)
                    c.setFillAlpha(1)
                    if m["tenggat"]["at"] >= as_of:
                        c.setStrokeColor(colors.HexColor(colour))
                        c.setLineWidth(1.2)
                        c.line(xd, yy - 3.5, xd, yy + 3.5)
                c.setFillColor(colors.white)
                c.circle(xt, yy, 4.2, stroke=0, fill=1)
                c.setFillColor(colors.HexColor(colour))
                c.circle(xt, yy, 3, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor(RULE))
        c.setLineWidth(0.6)
        c.line(self.L, bottom, right, bottom)
        for t, label in ticks:
            _axis_text(c, self._x(t), bottom - 9, label)


def _arrival_table(arr):
    """Tabel pendamping linimasa: kecamatan, kelurahan bantaran, dan per pos sumber jam tiba, tenggat, jarak."""
    lanes, as_of = arr["lanes"], arr["as_of"]
    lane_w = 96
    widths = [16, 86, WIDTH - 16 - 86 - lane_w * len(lanes)] + [lane_w] * len(lanes)
    head = [Paragraph("", S["th"]), Paragraph("Kecamatan", S["th"]), Paragraph("Kelurahan bantaran", S["th"])]
    head += [Paragraph(f"Dari {_t(lane['label'])}", S["th_r"]) for lane in lanes]
    data, style = [head], [
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RULE)),
    ]
    for i, row in enumerate(arr["rows"], 1):
        cells = [Paragraph(f'<font color="{MUTED}">{i}</font>', S["td"]), Paragraph(_t(row["kecamatan"]), S["td"]),
                 Paragraph(_t(", ".join(row["kelurahan"])) or "–", _style("kel", 7.5, 10, color=MUTED))]
        for lane in lanes:
            m = row["marks"].get(lane["station"])
            if not m:
                cells.append(Paragraph("–", S["td_r"]))
                continue
            lines = ([_clock_cell(m["tiba"], as_of, f'<font name="Geist-Medium">tiba {_clock(m["tiba"])}</font>')]
                     if m["tiba"] is not None else [])
            due = m["tenggat"]
            if due:
                lines.append(f'<font name="Geist-Bold" color="{CELL_INK[1]}">{_t(due["tindakan"])} segera</font>'
                             if due["now"] else f"{_t(due['tindakan'])} {_clock_cell(due['at'], as_of)}")
            lines.append(f'<font size=7 color="{MUTED}">{num_id(m["km"])} km · {_hours(m["jam"])}</font>')
            cells.append(Paragraph("<br/>".join(lines), S["td_r"]))
        data.append(cells)
        style.append(("LINEBELOW", (0, i), (-1, i), 0.5, colors.HexColor(SOFT_RULE)))
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _section(n, s, doc, counter):
    """Satu bagian sungai: kondisi pos, grafik TMA, wilayah terdampak (linimasa + tabel), rekomendasi tindakan."""
    unit, horizons = doc["unit"], doc["horizons"]
    names = join([st["label"] for st in s["stations"]])
    out = [Paragraph(f'{n}. {_t(s["title"])}', S["h2"]),
           Paragraph(f"Pos {_t(names)}", S["hint"]), Paragraph(f"{n}.1 Kondisi pos", S["h3"])]
    out += [Paragraph(_t(st["text"]), S["body_j"]) for st in s["stations"]]
    charts = [st["chart"] for st in s["stations"] if st["chart"]["actual"] or st["chart"]["forecast"]]
    if charts:
        starts = [ch["actual"][0][0] for ch in charts if ch["actual"]] or [ch["forecast"][0][0] for ch in charts]
        ends = [ch["forecast"][-1][0] for ch in charts if ch["forecast"]] + [ch["actual"][-1][0] for ch in charts
                                                                            if ch["actual"]]
        counter["fig"] += 1
        steps = max(len(ch["actual"]) for ch in charts)
        span = f"{steps} {unit} terakhir" + (f" dan prakiraan sampai +{horizons[-1]} {unit}" if horizons else "")
        out.append(KeepTogether([Spacer(1, 6), *[Hydrograph(ch, WIDTH, min(starts), max(ends)) for ch in charts],
                                 Paragraph(f"<b>Gambar {counter['fig']}.</b> Tinggi muka air (garis biru) dan hujan "
                                           f"di sel model (batang) Pos {_t(names)}: {span}. Garis titik = prakiraan, "
                                           "warna penanda = status pada nilai itu; pita warna = zona status siaga.",
                                           S["figcap"])]))
    out.append(Paragraph(f"{n}.2 Wilayah berpotensi terdampak", S["h3"]))
    if s["impact"]:
        out.append(Paragraph(_t(s["impact"]), S["body_j"]))
    if s["arrivals"]:
        arr = s["arrivals"]
        if unit == "jam" and arr["lanes"]:
            counter["fig"] += 1
            out.append(KeepTogether([Spacer(1, 6), ArrivalTimeline(arr, WIDTH, unit), Paragraph(
                f"<b>Gambar {counter['fig']}.</b> Perkiraan waktu tiba gelombang di kecamatan hilir, yang paling "
                "cepat terkena di atas. Batang = jendela tindakan dari tenggat SOP sampai gelombang tiba.",
                S["figcap"])]))
        counter["tab"] += 1
        out += [Paragraph(f"<b>Tabel {counter['tab']}.</b> Kecamatan dan kelurahan bantaran hilir"
                          + (", jam tiba, tenggat tindakan, dan jarak sepanjang sungai dari pos." if arr["lanes"]
                             else " (jarak sepanjang sungai belum tersedia)."), S["tabcap"]),
                _arrival_table(arr)]
    else:
        out.append(Paragraph("Belum ada data wilayah hilir untuk sungai ini.", S["body_j"]))
    if s["actions"]:
        out.append(Paragraph(f"{n}.3 Rekomendasi tindakan", S["h3"]))
        out += [Paragraph(_t(item), S["numbered"], bulletText=f"{i}.") for i, item in enumerate(s["actions"], 1)]
    return out


def _all_stations(doc):
    """Semua pos per aliran: papan duga, TMA sekarang dan prakiraan (sel berwarna = status), tren, hujan, sisa."""
    horizons, unit = doc["horizons"], doc["unit"]
    name_w, num_w, now_w, side_w, left_w = 88, 36, 42, 44, 52
    gauge_w = max(WIDTH - name_w - now_w - num_w * len(horizons) - 2 * side_w - left_w, 60)
    widths = [name_w, gauge_w, now_w] + [num_w] * len(horizons) + [side_w, side_w, left_w]
    head = ([Paragraph("Pos", S["th"]), Paragraph("Posisi terhadap batas siaga", S["th"]),
             Paragraph("Sekarang", S["th_r"])] + [Paragraph(f"+{h} {_t(unit)}", S["th_r"]) for h in horizons]
            + [Paragraph(f"Tren {doc['trend_steps']} {_t(unit)}", S["th_r"]), Paragraph("Hujan 24 jam", S["th_r"]),
               Paragraph("Sisa ke batas berikut", S["th_r"])])
    data, style, group = [head], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RULE)),
    ], object()
    for a in doc["assessments"]:
        r = a["row"]
        if r["aliran"] != group:
            group = r["aliran"]
            data.append([Paragraph(_t(f"Aliran {group}" if group else "Lainnya"), S["group"])] + [""] * (len(widths) - 1))
            i = len(data) - 1
            style += [("SPAN", (0, i), (-1, i)), ("TOPPADDING", (0, i), (-1, i), 10), ("BOTTOMPADDING", (0, i), (-1, i), 1)]
        row =[Paragraph(f"{_dot(r['status_by_h'].get(0))} {_t(r['label'])}", S["td"]), GaugeBar(r, gauge_w - 8)]
        i = len(data)
        for col, h in enumerate([0] + list(horizons), start=2):
            value, level = (r["now"] if h == 0 else r["forecasts"].get(h)), r["status_by_h"].get(h)
            ink = CELL_INK.get(level, INK)
            weight = "Geist-Medium" if h == 0 else "Geist-Regular"
            row.append(Paragraph(f'<font name="{weight}" color="{ink}">{_fmt(value)}</font>', S["td_r"]))
            if level in CELL_BG:
                style.append(("BACKGROUND", (col, i), (col, i), colors.HexColor(CELL_BG[level])))
        trend = ("–" if a["trend"] is None else "0,0" if a["trend"] == 0
                 else num_id(a["trend"], sign=True).replace("-", "−"))
        rain = "–" if a["rain_mm"] is None else num_id(a["rain_mm"])
        nxt = a["next"]
        left = ("–" if nxt is None
                else f'{num_id(nxt[2])}<br/><font size=7 color="{MUTED}">ke Siaga {nxt[0]}</font>')
        row += [Paragraph(trend, S["td_r"]), Paragraph(rain, S["td_r"]), Paragraph(left, S["td_r"])]
        data.append(row)
        style.append(("LINEBELOW", (0, i), (-1, i), 0.5, colors.HexColor(SOFT_RULE)))
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


class GaugeKey(Flowable):
    """Kunci papan duga, digambar dengan tanda yang sama: pita zona, tanda tinta TMA, titik biru puncak."""

    SIZE, GAP = 8, 14

    def __init__(self):
        super().__init__()
        self.items = [(f"z{lvl}", _status_word(lvl)) for lvl in (4, 3, 2, 1)]
        self.items += [("now", "TMA sekarang"), ("peak", "Puncak prakiraan")]

    def wrap(self, avail_w, _):
        self.width = avail_w
        return avail_w, 12

    def draw(self):
        c, x, mid = self.canv, 0.0, 5.0
        c.setFont("Geist-Regular", 8)
        for kind, label in self.items:
            if kind.startswith("z"):
                c.setFillColor(colors.HexColor(ZONE[int(kind[1])]))
                c.roundRect(x, mid - 2.5, 14, 5, 2.5, stroke=0, fill=1)
                x += 18
            elif kind == "now":
                c.setFillColor(colors.HexColor(INK))
                c.roundRect(x, mid - 5, 2, 10, 0.8, stroke=0, fill=1)
                x += 6
            else:
                c.setFillColor(colors.HexColor(LEVEL))
                c.circle(x + 2.7, mid, 2.7, stroke=0, fill=1)
                x += 9
            c.setFillColor(colors.HexColor(MUTED))
            c.drawString(x, mid - 2.8, label)
            x += pdfmetrics.stringWidth(label, "Geist-Regular", 8) + self.GAP


def _key():
    return [GaugeKey(), Paragraph("Angka dalam cm. Sel berwarna = status siaga pos pada waktu itu; papan duga memakai "
                                  "skala tiap pos, dari TMA terendah sampai batas Siaga 1.", S["hint"])]


def render(doc):
    """PDF (bytes) dari isi laporan `report.report_content`, berbentuk naskah: ringkasan, satu bagian per sungai
    (kondisi pos dan grafiknya, wilayah terdampak dan linimasanya, rekomendasi), pos lain, lalu lampiran."""
    out = BytesIO()
    pdf = BaseDocTemplate(out, pagesize=A4, title=f"{doc['title']} · {doc['stamp']}",
                          author="Flood Forecast", subject="Pantauan banjir Jakarta")
    # frame tanpa padding bawaan 6pt, supaya teks, panel dan tabel berbagi satu tepi kiri dan kanan
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, WIDTH, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    pdf.addPageTemplates([PageTemplate(id="laporan", frames=[frame])])
    from .pdf_cover import CoverPage  # di sini, bukan di atas: pdf_cover mengimpor token warna dari modul ini

    # sampul dulu (judul, waktu data dan status sudah di sana), lalu naskah mulai dari ringkasan
    story = [CoverPage(doc, doc["cover"]["gaya"]), PageBreak(), Paragraph("1. Ringkasan", S["h2"])]
    story += [Paragraph(_t(p), S["body_j"]) for p in doc["summary"]]
    story += [Spacer(1, 10), _lead(doc), Spacer(1, 8), _kpi_row(doc)]
    n, counter = 1, {"fig": 0, "tab": 0}
    for s in doc["sections"]:
        n += 1
        story += _section(n, s, doc, counter)
    if doc["watch"]:
        n += 1
        story.append(Paragraph(f"{n}. Pos lain yang dipantau", S["h2"]))
        story.append(Paragraph("Pos berikut masih Normal tetapi punya sinyal yang perlu dipantau. Tindakan: "
                               + _t(doc["pantau"]), S["body_j"]))
        story += [Paragraph(f"<b>{_t(w['label'])}</b> ({_t(_status_word(w['level']))}). {_t(w['text'])}", S["note"],
                            bulletText="•") for w in doc["watch"]]
    if not doc["sections"] and not doc["watch"]:
        story.append(Paragraph("Semua pos dalam batas wajar: tidak ada kenaikan status, kenaikan tajam, pos dekat "
                               "batas, hujan lebat, atau sinyal dari hulu. Lanjutkan pemantauan rutin.", S["body_j"]))
    # judul, kunci dan tabel satu blok: judul tidak tertinggal sendirian di kaki halaman
    counter["tab"] += 1
    story += [KeepTogether([Paragraph("Lampiran A. Status semua pos", S["h2"]),
                            Paragraph(f"<b>Tabel {counter['tab']}.</b> TMA sekarang dan prakiraan semua pos per aliran.",
                                      S["tabcap"]), *_key(), _all_stations(doc)]),
              Paragraph("Lampiran B. Dasar perhitungan dan keterbatasan", S["h2"]), Spacer(1, 4)]
    story += [Paragraph(_t(note), S["note"], bulletText="•") for note in doc["notes"]]
    pdf.build(story, canvasmaker=_canvas_class(doc))
    return out.getvalue()
