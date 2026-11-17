"""Sampul laporan PDF: satu halaman penuh yang digambar langsung di kanvas, tiga gaya (`laporan.sampul.gaya`).

    formal  rata tengah seperti sampul laporan dinas/akademik: judul, logo, status terparah, disusun untuk/oleh
    pita    separuh atas berwarna gelap menurut status terparah, judul status besar; angka utama dan tindakan di bawah
    peta    peta Jakarta sebagai gambar utama: kecamatan terdampak diarsir, pos diwarnai menurut statusnya

Isi semua gaya dari dokumen yang sama (report.report_content): banner status, headline (report_sections.headline)
dan keterangan sampul. Dipanggil dari pdf.render; mengimpor token warna dan helper dari pdf.
"""

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable, Paragraph

from .figures import KECAMATAN, REGION_FILL, REGIONS, SIAGA_NAME, SUNGAI
from .pdf import (CELL_BG, CELL_INK, INK, LEVEL, MARGIN_BOTTOM, MARGIN_X, MUTED, NO_STATUS, PAGE_H, PAGE_W, RULE,
                  STATUS, _mark, _style, _t)
from .report_sections import urgent_text

BULAN_PANJANG = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
                 "November", "Desember")
DARK = {1: "#7f1d1d", 2: "#8a3412", 3: "#6b4a00", 4: "#16345c", None: "#2b2f36"}  # pita: gelap menurut status
MAP_BOX = (106.665, -6.41, 106.98, -6.08)  # bingkai peta yang sama dengan build_wilayah.PETA
STYLES = ("formal", "pita", "peta")


def _long(ts):
    return f"{ts.day} {BULAN_PANJANG[ts.month - 1]} {ts.year}, pukul {ts:%H.%M} WIB"


def _status_label(level):
    return "Tanpa status" if level is None else "Normal" if level == 4 else f"Siaga {level} · {SIAGA_NAME[level]}"


class CoverPage(Flowable):
    """Satu halaman penuh; menggambar dalam koordinat halaman (titik 0,0 = kiri bawah kertas)."""

    def __init__(self, doc, style="formal"):
        super().__init__()
        self.doc, self.style = doc, style if style in STYLES else "formal"

    def wrap(self, avail_w, avail_h):
        self.width, self.height = avail_w, avail_h
        return avail_w, avail_h

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(-MARGIN_X, -MARGIN_BOTTOM)
        getattr(self, f"_{self.style}")(c)
        if self.doc["cover"]["demo"]:
            self._demo(c)
        c.restoreState()

    # ---------- helpers ----------
    def _text(self, c, x, y, text, size, font="Geist-Regular", color=INK, anchor="start", space=0.0, alpha=1.0):
        c.setFont(font, size)
        c.setFillColor(colors.HexColor(color))
        c.setFillAlpha(alpha)
        width = pdfmetrics.stringWidth(text, font, size) + space * max(len(text) - 1, 0)
        x0 = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
        t = c.beginText(x0, y)
        t.setFont(font, size)
        t.setCharSpace(space)
        t.textOut(text)
        t.setCharSpace(0)  # Tc bertahan di status teks PDF: tanpa ini paragraf sesudahnya ikut renggang
        c.drawText(t)
        c.setFillAlpha(1)
        return width

    def _para(self, c, html, style, x, top, width):
        """Paragraf dengan sisi atas di `top`; mengembalikan tingginya."""
        p = Paragraph(html, style)
        _, h = p.wrap(width, 1000)
        p.drawOn(c, x, top - h)
        return h

    def _demo(self, c):
        text = self.doc["cover"]["demo"].upper()
        w = pdfmetrics.stringWidth(text, "Geist-Bold", 8) + 16
        x, y = PAGE_W - MARGIN_X - w, PAGE_H - 34
        c.setFillColor(colors.HexColor(STATUS[1]))
        c.roundRect(x, y - 5, w, 17, 4, stroke=0, fill=1)
        self._text(c, x + 8, y, text, 8, "Geist-Bold", "#ffffff")

    def _numbers(self, c, x, top, width, ink=INK, sub=MUTED):
        """Tiga angka utama sejajar: pos di atas Normal, kecamatan terdampak, gelombang paling cepat."""
        k, head, as_of = self.doc["kpis"], self.doc["headline"], self.doc.get("as_of")
        graded = len(k["levels"])
        first = head["firsts"][0] if head["firsts"] else None
        cells = [("Pos di atas Normal", f"{graded - k['normal']}/{graded}",
                  ", ".join(k["off"]) if k["off"] else "Semua pos Normal"),
                 ("Kecamatan berpotensi terdampak", str(head["kecamatan"]) if head["kecamatan"] else "–",
                  f"{head['kelurahan']} kelurahan" if head["kecamatan"] else "Tidak ada"),
                 ("Gelombang paling cepat tiba", f"{first['tiba']:%H:%M}" if first else "–",
                  (f"Kec. {first['kecamatan']}" + (f", {first['tiba'].day} {BULAN_PANJANG[first['tiba'].month - 1][:3]}"
                                                   if as_of is not None and first["tiba"].normalize()
                                                   != as_of.normalize() else "")) if first else "Belum ada")]
        col = (width - 2 * 20) / 3
        for i, (label, big, note) in enumerate(cells):
            x0 = x + i * (col + 20)
            self._text(c, x0, top - 9, label, 8.5, color=sub)
            self._text(c, x0, top - 40, big, 28, "Geist-Bold", ink)
            self._para(c, _t(note), _style("cn", 8, 11, color=sub), x0, top - 48, col)

    def _urgent_html(self):
        head, as_of = self.doc["headline"], self.doc.get("as_of")
        if head["urgent"]:
            return f'<font name="Geist-Bold">Tindakan paling mendesak:</font> {_t(urgent_text(head["urgent"], as_of))}.'
        if self.doc["sections"] or self.doc["watch"]:
            return '<font name="Geist-Bold">Belum ada tenggat persiapan atau evakuasi.</font> Lanjutkan pemantauan.'
        return '<font name="Geist-Bold">Tidak ada tindakan khusus.</font> Lanjutkan pemantauan rutin.'

    def _meta(self):
        cover, doc = self.doc["cover"], self.doc
        rows = [("Nomor", cover["number"]), ("Dibuat", cover["made"]),
                ("Cakupan prakiraan", f"sampai +{doc['horizons'][-1]} {doc['unit']}" if doc["horizons"] else "–"),
                ("Kepada", cover["kepada"]), ("Disusun oleh", cover["disusun_oleh"])]
        return [(k, v) for k, v in rows if v]

    # ---------- A. formal ----------
    def _formal(self, c):
        doc, cover, b = self.doc, self.doc["cover"], self.doc["banner"]
        cx, as_of = PAGE_W / 2, doc.get("as_of")
        self._text(c, cx, PAGE_H - 132, "LAPORAN", 10, "Geist-Medium", MUTED, "middle", space=3)
        self._text(c, cx, PAGE_H - 172, "PANTAUAN DAN PRAKIRAAN BANJIR", 24, "Geist-Bold", INK, "middle", space=0.6)
        self._text(c, cx, PAGE_H - 200, "PROVINSI DKI JAKARTA", 15, "Geist-Medium", INK, "middle", space=1.5)
        c.setStrokeColor(colors.HexColor(INK))
        c.setLineWidth(1.2)
        c.line(cx - 30, PAGE_H - 222, cx + 30, PAGE_H - 222)
        self._text(c, cx, PAGE_H - 246, f"Data per {_long(as_of)}" if as_of is not None else "Data belum ada", 11,
                   color="#3a3a3a", anchor="middle")
        size = 104
        _mark(c, cx - size / 2, PAGE_H / 2 - size / 2 + 30, size)

        level = b["level"]
        label = b["head"]
        w = pdfmetrics.stringWidth(label, "Geist-Medium", 10.5) + 40
        y = PAGE_H / 2 - 74
        c.setFillColor(colors.HexColor(CELL_BG.get(level, "#f2f4f7")))
        c.setStrokeColor(colors.HexColor(STATUS.get(level, NO_STATUS)))
        c.setLineWidth(0.8)
        c.roundRect(cx - w / 2, y - 9, w, 26, 13, stroke=1, fill=1)
        c.setFillColor(colors.HexColor(STATUS.get(level, NO_STATUS)))
        c.circle(cx - w / 2 + 15, y + 4, 3.5, stroke=0, fill=1)
        self._text(c, cx - w / 2 + 25, y, label, 10.5, "Geist-Medium", CELL_INK.get(level, INK))
        self._para(c, self._urgent_html(), _style("fu", 9.5, 14, color="#3a3a3a", alignment=TA_CENTER),
                   cx - 200, y - 22, 400)

        y = 250
        for key in ("kepada", "disusun_oleh"):
            if cover[key]:
                self._text(c, cx, y, "Disusun untuk" if key == "kepada" else "Disusun oleh", 9, color=MUTED,
                           anchor="middle")
                self._text(c, cx, y - 18, cover[key], 12, "Geist-Medium", INK, "middle")
                y -= 52
        self._text(c, cx, 96, "FLOOD FORECAST · JAKARTA", 10, "Geist-Bold", INK, "middle", space=2)
        self._text(c, cx, 78, f"Nomor {cover['number']} · dibuat {cover['made']}", 8.5, color=MUTED, anchor="middle")

    # ---------- B. pita ----------
    def _pita(self, c):
        doc, b = self.doc, self.doc["banner"]
        level, as_of = b["level"], doc.get("as_of")
        band = PAGE_H * 0.52
        c.setFillColor(colors.HexColor(DARK.get(level, DARK[None])))
        c.rect(0, PAGE_H - band, PAGE_W, band, stroke=0, fill=1)
        x, width = MARGIN_X + 6, PAGE_W - 2 * MARGIN_X - 12
        # logo putih di atas pita
        _mark(c, x, PAGE_H - 47, 14, fill="#ffffff", wave=DARK.get(level, DARK[None]))
        self._text(c, x + 20, PAGE_H - 44, "Flood Forecast", 10, "Geist-Medium", "#ffffff")
        self._text(c, x + 20 + pdfmetrics.stringWidth("Flood Forecast ", "Geist-Medium", 10), PAGE_H - 44,
                   "· Jakarta", 10, color="#ffffff", alpha=0.7)

        top = PAGE_H - 150
        self._text(c, x, top, "LAPORAN PANTAUAN DAN PRAKIRAAN BANJIR · PROVINSI DKI JAKARTA", 8.5, "Geist-Bold",
                   "#ffffff", space=1.2, alpha=0.75)
        h = self._para(c, _t(b["head"]), _style("ph", 38, 43, "Geist-Bold", color="#ffffff"), x, top - 16, width)
        h += self._para(c, _t(b["text"]), _style("pt", 11.5, 16, color="#ffffff"), x, top - 30 - h, width * 0.85)

        # status per waktu, di kaki pita
        cols = b["worst"]
        gap, y = 14, PAGE_H - band + 40
        w = (width - gap * (len(cols) - 1)) / len(cols)
        self._text(c, x, y + 46, f"Data per {_long(as_of)}" if as_of is not None else "Data belum ada", 9,
                   color="#ffffff", alpha=0.75)
        for i, col in enumerate(cols):
            x0 = x + i * (w + gap)
            self._text(c, x0, y + 22, col["label"], 8.5, "Geist-Bold", "#ffffff", alpha=0.75)
            c.setFillColor(colors.HexColor(CELL_BG.get(col["level"], "#d9dde3")))
            c.roundRect(x0, y + 12, w, 4, 2, stroke=0, fill=1)
            self._text(c, x0, y - 4, SIAGA_NAME[col["level"]] if col["level"] else "–", 13, "Geist-Bold", "#ffffff")

        top = PAGE_H - band - 44
        self._numbers(c, x, top, width)
        c.setStrokeColor(colors.HexColor(RULE))
        c.setLineWidth(0.6)
        c.line(x, top - 92, x + width, top - 92)
        h = self._para(c, self._urgent_html(), _style("pu", 11, 16), x, top - 108, width)
        y = top - 130 - h
        meta = self._meta()
        col = width / 3
        for i, (k, v) in enumerate(meta):
            x0, y0 = x + (i % 3) * col, y - (i // 3) * 36
            self._text(c, x0, y0, k, 8, color=MUTED)
            self._para(c, _t(v), _style("pm", 9.5, 12.5), x0, y0 - 5, col - 12)
        self._para(c, "Angka prakiraan dan waktu tiba adalah perkiraan model, bukan kepastian; dasar perhitungannya ada "
                   "di Lampiran B. Keputusan operasional tetap mengikuti arahan BPBD Provinsi DKI Jakarta.",
                   _style("pn", 7.5, 10.5, color=MUTED), x, 74, width)

    # ---------- C. peta ----------
    def _peta(self, c):
        doc, b = self.doc, self.doc["banner"]
        as_of, x, width = doc.get("as_of"), MARGIN_X, PAGE_W - 2 * MARGIN_X
        _mark(c, x, PAGE_H - 46, 14)
        self._text(c, x + 20, PAGE_H - 42, "Flood Forecast", 10, "Geist-Medium")
        self._text(c, x + 20 + pdfmetrics.stringWidth("Flood Forecast ", "Geist-Medium", 10), PAGE_H - 42, "· Jakarta",
                   10, color=MUTED)
        self._text(c, x, PAGE_H - 96, "LAPORAN", 8.5, "Geist-Bold", MUTED, space=2)
        self._text(c, x, PAGE_H - 126, "Pantauan dan Prakiraan Banjir", 26, "Geist-Bold")
        self._text(c, x, PAGE_H - 148, "Provinsi DKI Jakarta · " + (f"data per {_long(as_of)}" if as_of is not None
                                                                     else "data belum ada"), 11, color="#3a3a3a")
        level = b["level"]
        y = PAGE_H - 182
        c.setFillColor(colors.HexColor(STATUS.get(level, NO_STATUS)))
        c.circle(x + 5, y + 4, 5, stroke=0, fill=1)
        self._text(c, x + 16, y, b["head"], 13, "Geist-Bold", CELL_INK.get(level, INK))

        # peta: bingkai lon/lat sama dengan peta dashboard, skala x dikoreksi cos(lintang)
        lon0, lat0, lon1, lat1 = MAP_BOX
        top, bottom = PAGE_H - 206, 262
        sx = 0.9945  # cos(6,2°)
        scale = min(width / ((lon1 - lon0) * sx), (top - bottom) / (lat1 - lat0))
        mw, mh = (lon1 - lon0) * sx * scale, (lat1 - lat0) * scale
        ox, oy = x + (width - mw) / 2, bottom + (top - bottom - mh) / 2
        px = lambda lon: ox + (lon - lon0) * sx * scale  # noqa: E731
        py = lambda lat: oy + (lat - lat0) * scale  # noqa: E731

        c.saveState()
        clip = c.beginPath()
        clip.rect(ox, oy, mw, mh)
        c.clipPath(clip, stroke=0, fill=0)

        def polygon(feature, fill, stroke, width_):
            path = c.beginPath()
            for poly in feature["geometry"]["coordinates"]:
                ring = poly[0]
                path.moveTo(px(ring[0][0]), py(ring[0][1]))
                for lon, lat in ring[1:]:
                    path.lineTo(px(lon), py(lat))
                path.close()
            c.setFillColor(colors.HexColor(fill))
            c.setStrokeColor(colors.HexColor(stroke))
            c.setLineWidth(width_)
            c.drawPath(path, stroke=1 if width_ else 0, fill=1)

        for f in REGIONS["features"]:
            polygon(f, REGION_FILL.get(f["properties"]["name"], "#e3e7ed"), "#ffffff", 1.6)
        hit = {}
        for s in doc["sections"]:
            for row in (s["arrivals"] or {}).get("rows", []):
                hit[row["kecamatan"]] = min(hit.get(row["kecamatan"], 5), s["level"])
        for f in KECAMATAN["features"]:
            name = f["properties"]["name"]
            if name in hit:
                polygon(f, CELL_BG.get(hit[name], "#dfe9f8"), "#ffffff", 0.6)
            else:
                polygon(f, "#e3e7ed", "#f7f8fa", 0.4)
        rivers = {s["river"] for s in doc["sections"]}
        for f in SUNGAI["features"]:
            geom = f["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            on = f["properties"]["name"] in rivers
            c.setStrokeColor(colors.HexColor(LEVEL if on else "#a9c1e3"))
            c.setLineWidth(1.5 if on else 0.8)
            c.setLineJoin(1)
            for part in parts:
                path = c.beginPath()
                path.moveTo(px(part[0][0]), py(part[0][1]))
                for lon, lat in part[1:]:
                    path.lineTo(px(lon), py(lat))
                c.drawPath(path, stroke=1, fill=0)
        c.restoreState()

        for a in doc["assessments"]:  # pos: titik status; yang di luar bingkai (Katulampa) di tepi bawah
            r = a["row"]
            if r.get("lat") is None:
                continue
            levels = [s for s in (a["now_level"], a["worst"]) if s is not None]
            lvl = min(levels) if levels else None
            lon, lat = r["lon"], r["lat"]
            out = lat < lat0
            X, Y = px(lon), (oy + 6 if out else py(lat))
            c.setFillColor(colors.white)
            c.circle(X, Y, 6, stroke=0, fill=1)
            c.setFillColor(colors.HexColor(STATUS.get(lvl, NO_STATUS)))
            c.circle(X, Y, 4.5, stroke=0, fill=1)
            label = r["label"] + (" ↓ Bogor" if out else "")
            # sisi label dari config/dashboard.yaml (sama dengan peta dashboard); pos di luar bingkai: kiri, supaya
            # tidak menimpa label pos yang tepat di dalam tepi (Depok)
            left = out or r.get("side") == "left"
            self._text(c, X + (-8 if left else 8), Y - 3, label, 7.5, "Geist-Medium", INK, "end" if left else "start")
        c.setStrokeColor(colors.HexColor(RULE))
        c.setLineWidth(0.6)
        c.rect(ox, oy, mw, mh, stroke=1, fill=0)

        # legenda
        y = oy - 16
        lx = ox
        for lvl in (1, 2, 3, 4):
            c.setFillColor(colors.HexColor(STATUS[lvl]))
            c.circle(lx + 4, y + 3, 4, stroke=0, fill=1)
            lx += 11 + self._text(c, lx + 11, y, "Normal" if lvl == 4 else f"Siaga {lvl}", 7.5, color=MUTED) + 12
        c.setFillColor(colors.HexColor(CELL_BG[2]))
        c.rect(lx, y - 1, 12, 8, stroke=0, fill=1)
        lx += 16 + self._text(c, lx + 16, y, "kecamatan terdampak", 7.5, color=MUTED) + 12
        c.setStrokeColor(colors.HexColor(LEVEL))
        c.setLineWidth(1.5)
        c.line(lx, y + 3, lx + 14, y + 3)
        self._text(c, lx + 18, y, "sungai berstatus siaga", 7.5, color=MUTED)

        top = oy - 40
        self._numbers(c, x, top, width)
        h = self._para(c, self._urgent_html(), _style("mu", 10.5, 15), x, top - 96, width)
        meta = " · ".join(f"{k}: {v}" for k, v in self._meta())
        self._para(c, _t(meta), _style("mm", 8, 11, color=MUTED), x, top - 108 - h, width)

