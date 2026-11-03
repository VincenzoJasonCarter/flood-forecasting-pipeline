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
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from .figures import SIAGA_NAME, gauge

_FONT_DIR = Path(__file__).with_name("fonts")
for _weight in ("Regular", "Medium", "Bold"):
    pdfmetrics.registerFont(TTFont(f"Geist-{_weight}", str(_FONT_DIR / f"Geist-{_weight}.ttf")))
pdfmetrics.registerFontFamily("Geist", normal="Geist-Regular", bold="Geist-Medium",
                              italic="Geist-Regular", boldItalic="Geist-Medium")

# token dashboard.css
INK, MUTED, RULE, SOFT_RULE = "#0a0a0a", "#6b6b6b", "#e6e6e6", "#f0f0f0"
RAISED, LEVEL, NO_STATUS = "#f2f4f7", "#1d5fbf", "#9a9c9e"
STATUS = {4: "#3d3d3d", 3: "#d49a00", 2: "#d9620f", 1: "#c4242a"}
CELL_BG = {3: "#fff4d6", 2: "#ffe9d9", 1: "#ffe4e1"}
CELL_INK = {3: "#7a4a00", 2: "#9a3412", 1: "#831c1e"}
ZONE = {4: "#e3e7ed", 3: "#f9ebc0", 2: "#f8d9c2", 1: "#f3c9c6"}

PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 18 * mm, 24 * mm, 22 * mm
WIDTH = PAGE_W - 2 * MARGIN_X


def _style(name, size, leading, font="Geist-Regular", color=INK, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, textColor=colors.HexColor(color), **kw)


S = {
    "h1": _style("h1", 22, 28, "Geist-Medium"),
    "meta": _style("meta", 8.5, 12, color=MUTED, spaceBefore=4),
    "h2": _style("h2", 13, 18, "Geist-Medium", spaceBefore=22, keepWithNext=1),
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
    return "–" if value is None else f"{value:.1f}".replace("-", "−")


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


def _lead(doc):
    """Panel pembuka: status terparah besar di kiri, temuan dan poin-poinnya di kanan."""
    level = doc["severest"]
    sub = (SIAGA_NAME[level] if level is not None and level < 4 else "Siaga 4" if level == 4
           else "Belum bisa dinilai")
    left = [Paragraph(_t(f"Terparah {doc['span']}"), S["label"]),
            Paragraph(f"{_dot(level, 13)} {_t(_status_word(level))}", S["status"]),
            Paragraph(_t(sub), S["label"])]
    right = [Paragraph(_t(doc["finding"]), S["finding"])]
    right += [Paragraph(_t(b), S["bullet"], bulletText="–") for b in doc["bullets"]]
    table = Table([[left, right]], colWidths=[142, WIDTH - 142])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(RAISED)),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 13), ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, colors.HexColor("#dde1e7")),
    ]))
    return table


def _chips(a, unit):
    r, now, worst = a["row"], a["now_level"], a["worst"]
    head = (f"{_dot(now)} {_status_word(now)}" + (f" · {SIAGA_NAME[now]}" if now and now < 4 else "")
            if now is not None else f"{_dot(None)} {'TMA tidak terbaca' if r['limits'] else 'Tanpa ambang'}")
    if worst is not None and worst < (now or 4):
        head += (f'  <font color="{MUTED}">→</font>  {_dot(worst)} Siaga {worst} · {SIAGA_NAME[worst]}'
                 f'  <font color="{MUTED}">+{a["worst_h"]} {_t(unit)}</font>')
    return Paragraph(head, S["chips"])


def _caption(a, unit):
    r, nxt = a["row"], a["next"]
    text = f"<b>{_fmt(r['now'])} cm</b>" if r["now"] is not None else "TMA tidak terbaca"
    if nxt:
        text += f" · {nxt[2]:.1f} cm lagi ke Siaga {nxt[0]}"
    elif a["now_level"] == 1:
        text += " · di atas batas Siaga 1"
    if r["peak"] is not None:
        text += f'<br/><font color="{LEVEL}">Puncak prakiraan {_fmt(r["peak"])} cm, +{r["peak_h"]} {_t(unit)}</font>'
    return Paragraph(text, S["caption"])


def _item(a, unit):
    """Satu pos yang perlu perhatian: nama dan status, lalu alasan di kiri; papan duga dan tindakan di kanan."""
    r = a["row"]
    where = (f"Aliran {r['aliran']} · " if r["aliran"] else "") + "TMA dalam cm"
    left_w, right_w = WIDTH * 0.55, WIDTH * 0.45
    action = Table([[[Paragraph("Tindakan", S["label"]), Paragraph(_t(a["action"]), S["act"])]]],
                   colWidths=[right_w - 14])
    action.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(RAISED)), ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    reasons = [Paragraph(_t(x), S["bullet"], bulletText="–") for x in a["reasons"]]
    if a.get("hilir"):
        areas = "; ".join(f"<b>{_t(kec)}</b>: {_t(', '.join(kel))}" for kec, kel in a["hilir"].items())
        reasons += [Spacer(1, 8), Paragraph("Wilayah hilir (perkiraan), kecamatan: kelurahan", S["label"]),
                    Paragraph(areas, S["areas"])]
    right = [GaugeBar(r, right_w - 14), _caption(a, unit), Spacer(1, 8), action]
    table = Table([
        [[Paragraph(_t(r["station"]), S["name"]), Paragraph(_t(where), S["label"])], _chips(a, unit)],
        [reasons, right],
    ], colWidths=[left_w, right_w])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 18),
        ("LEFTPADDING", (1, 0), (1, -1), 14), ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
        ("LINEBELOW", (0, 1), (-1, 1), 0.6, colors.HexColor(RULE)),
    ]))
    return KeepTogether([table])


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
        trend = ("–" if a["trend"] is None else "0.0" if a["trend"] == 0
                 else f"{a['trend']:+.1f}".replace("-", "−"))
        rain = "–" if a["rain_mm"] is None else f"{a['rain_mm']:.1f}"
        nxt = a["next"]
        left = ("–" if nxt is None
                else f'{nxt[2]:.1f}<br/><font size=7 color="{MUTED}">ke Siaga {nxt[0]}</font>')
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
             Spacer(1, 14), _lead(doc),
             Paragraph("Perlu perhatian", S["h2"]),
             Paragraph("Diurutkan dari status terparah. Alasan = sinyal yang membuat pos masuk daftar ini.", S["hint"])]
    if doc["attention"]:
        story += [_item(a, unit) for a in doc["attention"]]
    else:
        story.append(Paragraph("Semua pos dalam batas wajar: tidak ada kenaikan status, kenaikan tajam, pos dekat batas, "
                               "hujan lebat, atau sinyal dari hulu. Lanjutkan pemantauan rutin.", S["body"]))
    # judul, kunci dan tabel satu blok: judul tidak tertinggal sendirian di kaki halaman
    story += [KeepTogether([Paragraph("Semua pos", S["h2"]), Spacer(1, 4), *_key(), _all_stations(doc)]),
              Paragraph("Catatan data dan keterbatasan", S["h2"]), Spacer(1, 4)]
    story += [Paragraph(_t(n), S["note"], bulletText="–") for n in doc["notes"]]
    pdf.build(story, canvasmaker=_canvas_class(doc))
    return out.getvalue()
