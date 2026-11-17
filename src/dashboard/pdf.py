"""Laporan unduhan sebagai PDF A4 (ReportLab, murni Python): isi dari `report.report_content`, rupa dari dashboard.

Bahasa visualnya sama dengan dashboard: Geist (dibundel di fonts/, SIL OFL), tinta dan abu-abu untuk teks,
warna hanya untuk status siaga, dan papan duga mini per pos (zona siaga, TMA sekarang, puncak prakiraan biru).
"""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, HRFlowable, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .figures import SIAGA_NAME, gauge, river_label
from .overview import card_figure, id_text, limit_line, num_id, rain_band

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

REST_LINE = 22  # ruang untuk baris "Juga perlu perhatian" di bawah kartu
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


def _mark(c, x, y, size):
    """Logo dashboard (assets/mark.svg): lingkaran tinta dengan dua gelombang putih; (x, y) = kiri bawah."""
    s = size / 24
    c.setFillColor(colors.HexColor(INK))
    c.circle(x + 12 * s, y + 12 * s, 12 * s, stroke=0, fill=1)
    c.setStrokeColor(colors.white)
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
            for number, state in enumerate(self._states, 1):
                self.__dict__.update(state)
                self._chrome(number, len(self._states))
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


def _chips(a, unit):
    r, now, worst = a["row"], a["now_level"], a["worst"]
    head = (f'<font color="{CELL_INK[now]}">{_dot(now)} <font name="Geist-Bold">{SIAGA_NAME[now]} · Siaga {now}</font></font>'
            if now is not None else f"{_dot(None)} {'TMA tidak terbaca' if r['limits'] else 'Tanpa ambang'}")
    if worst is not None and worst < (now or 4):
        head += (f'<br/><font color="{MUTED}">→</font> <font color="{CELL_INK[worst]}">{_dot(worst)} '
                 f'<font name="Geist-Bold">Siaga {worst} · {SIAGA_NAME[worst]}</font></font>'
                 f' <font color="{MUTED}">+{a["worst_h"]} {_t(unit)}</font>')
    return Paragraph(head, S["chips"])


def _caption(a, unit):
    r = a["row"]
    text = f"<b>{_fmt(r['now'])} cm</b> sekarang" if r["now"] is not None else "TMA tidak terbaca"
    limit = limit_line(a)
    if limit:
        text += f"<br/>{_t(limit)}"
    elif a["now_level"] == 1:
        text += "<br/>Di atas batas Siaga 1"
    if r["peak"] is not None:
        text += f'<br/><font color="{LEVEL}">{_fmt(r["peak"])} cm puncak +{r["peak_h"]} {_t(unit)}</font>'
    return Paragraph(text, S["caption"])


def _short(text):
    """Klausa pertama tindakan (sampai ';'); teks lengkapnya ada di dashboard dan config."""
    head, _, rest = text.partition(";")
    return head.strip() + (" …" if rest else "")


def _item(i, a, unit, rise_cm, trend_steps):
    """Satu pos yang perlu perhatian, ringkas: nama, angka utama dan alasan pertama di kiri; status, papan duga dan
    tindakan di kanan; satu baris kecamatan hilir di bawahnya."""
    r = a["row"]
    big, line = card_figure(a, unit, rise_cm, trend_steps)
    river = river_label(r["station"]) or (f"Aliran {r['aliran']}" if r["aliran"] else "")
    left_w, right_w = WIDTH * 0.52, WIDTH * 0.48
    name = Paragraph(f'<font name="Geist-Bold" size=11>{_t(r["label"])}</font>'
                     f'<font color="{MUTED}" size=8>   #{i}{" · " + _t(river) if river else ""}</font>', S["body"])
    figure = Paragraph(f'<font name="Geist-Bold" size=15 color="{BLUE_INK}">{_t(big)}{"" if big == "–" else " cm"}</font>'
                       f'  <font size=8.5>{_t(line)}</font>', _style("fig", 9, 18, spaceBefore=3))
    reasons = [Paragraph(_t(id_text(a["reasons"][0])), _style("why", 8.5, 12, spaceBefore=2))]
    if len(a["reasons"]) > 1:
        reasons.append(Paragraph(f"+{len(a['reasons']) - 1} alasan lain di laporan lengkap",
                                 _style("more", 7.5, 10, color=MUTED, spaceBefore=1)))
    action = Table([[Paragraph(f'<font name="Geist-Bold" size=7 color="{BLUE_INK}">TINDAKAN  </font>{_t(_short(a["action"]))}',
                               _style("act", 8, 11))]], colWidths=[right_w - 12])
    action.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BLUE_BG)), ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    right = [_chips(a, unit), Spacer(1, 3), GaugeBar(r, right_w - 12, 10), _caption(a, unit), Spacer(1, 4), action]
    if a.get("hilir"):
        names = list(a["hilir"])
        shown = ", ".join(names[:3]) + (f" +{len(names) - 3} kec." if len(names) > 3 else "")
        reasons.append(Paragraph(f"Hilir (perkiraan): {_t(shown)}", _style("hil", 7.5, 10, color=MUTED, spaceBefore=3)))
    table = Table([[[name, figure, *reasons], right]], colWidths=[left_w, right_w])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 14),
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RULE)),
    ]))
    return table


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
    """PDF (bytes) dari isi laporan `report.report_content`."""
    out = BytesIO()
    pdf = BaseDocTemplate(out, pagesize=A4, title=f"{doc['title']} · {doc['stamp']}",
                          author="Flood Forecast", subject="Pantauan banjir Jakarta")
    # frame tanpa padding bawaan 6pt, supaya teks, panel dan tabel berbagi satu tepi kiri dan kanan
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, WIDTH, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    pdf.addPageTemplates([PageTemplate(id="laporan", frames=[frame])])
    unit = doc["unit"]
    story = [Paragraph(_t(doc["title"]), S["h1"]), Paragraph(_t(" · ".join(doc["meta"])), S["meta"]),
             Spacer(1, 8), _lead(doc), Spacer(1, 8), _kpi_row(doc),
             *([Paragraph(f"Surut dalam {doc['trend_steps']} {_t(unit)} terakhir: {_t(', '.join(doc['falling']))}.", S["hint"])]
               if doc["falling"] else []),
             Paragraph(f"{doc['attention_title']} · {len(doc['attention'])} dari {len(doc['assessments'])} pos"
                       if doc["attention"] else "Perlu perhatian", S["h2"]), Spacer(1, 2)]
    if doc["attention"]:
        # sebanyak mungkin kartu yang muat di halaman pertama (di bawah banner dan angka); sisanya hanya disebut namanya
        room = frame._height - sum(f.wrap(WIDTH, frame._height)[1] + f.getSpaceBefore() + f.getSpaceAfter() for f in story)
        shown = []
        for i, a in enumerate(doc["attention"], 1):
            card = _item(i, a, unit, doc["rise_cm"], doc["trend_steps"])
            height = card.wrap(WIDTH, frame._height)[1]
            more = i < len(doc["attention"])
            if shown and height + (REST_LINE if more else 0) > room:
                break
            room -= height
            shown.append(card)
        story += [KeepTogether([card]) for card in shown]
        rest = doc["attention"][len(shown):]
        if rest:
            story.append(Paragraph(f"Juga perlu perhatian: {_t(', '.join(x['row']['label'] for x in rest))}. "
                                   "Statusnya ada di tabel Semua pos.", _style("rest", 8.5, 12, color=MUTED, spaceBefore=6)))
    else:
        story.append(Paragraph("Semua pos dalam batas wajar: tidak ada kenaikan status, kenaikan tajam, pos dekat batas, "
                               "hujan lebat, atau sinyal dari hulu. Lanjutkan pemantauan rutin.", S["body"]))
    # judul, kunci dan tabel satu blok: judul tidak tertinggal sendirian di kaki halaman
    story += [KeepTogether([Paragraph("Semua pos", S["h2"]), Spacer(1, 4), *_key(), _all_stations(doc)]),
              Paragraph("Catatan data dan keterbatasan", S["h2"]), Spacer(1, 4)]
    story += [Paragraph(_t(n), S["note"], bulletText="•") for n in doc["notes"]]
    pdf.build(story, canvasmaker=_canvas_class(doc))
    return out.getvalue()
