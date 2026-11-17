"""Bangun ulang data wilayah dashboard dari OpenStreetMap: `make wilayah`.

Menulis empat file di src/dashboard/ (dibundel, dashboard tidak memanggil internet saat jalan):
    kota.geojson       5 kota DKI (gabungan kecamatan di bawah, jadi garisnya pas) + Depok, Tangerang dan
                       Tangerang Selatan sebagai konteks, dipotong ke PETA
    kecamatan.geojson  42 kecamatan DKI daratan (admin_level 6), disederhanakan, untuk peta
    sungai.geojson     alur sungai yang dipantau tiap pos di dalam DKI, plus alur hulu dari titik pos
                       (config/dashboard.yaml) sampai alur DKI itu (properti `pos`)
    hilir.json         kelurahan dan kecamatan di bantaran hilir tiap pos (PERKIRAAN, lihat di bawah), plus
                       jarak sepanjang sungai dari pos ke tiap kecamatan (`kecamatan_km`) untuk waktu tempuh

Sumber: OpenStreetMap lewat Overpass API (© OpenStreetMap contributors, ODbL 1.0), jadi keempat file
ini juga ODbL. Tidak ada data resmi pos -> wilayah terdampak yang bisa diunduh, jadi bantaran
DITURUNKAN: alur sungai pos (way OSM bernama sungai itu, disambung lewat ruas tanpa nama searah
aliran) di dalam DKI ditambah alur hulu dari titik pos, mulai dari lintang pos (sungai-sungai ini
mengalir ke utara), diberi buffer BUFFER_M, lalu kelurahan yang terkena. Ciliwung dan Krukut
dipotong di pintu air tujuan menurut SOP BPBD (Pedoman Pengendalian Banjir 2020, hlm. 10:
Depok -> PA Manggarai, Krukut Hulu -> PA Karet): hilir pintu air itu diatur pintunya sendiri.
Pesanggrahan dan Angke sampai laut lewat Cengkareng Drain (SOP: "sampai di PA Cengkareng Drain").

Hasilnya dicek ke daftar kelurahan yang disebut BPBD DKI di peringatan dini (dikutip media, REFERENSI)
dan recall-nya dicetak.

Jarak ke kecamatan = jalur terpendek di jaringan way air OSM dari titik pos, hanya lewat ruas di koridor
alur pos (alur yang belum dipotong batas DKI, supaya meander yang keluar-masuk DKI tidak memutus jalur),
sampai node pertama dalam BUFFER_M dari kecamatan itu. Katulampa di luar bingkai: jaraknya = Katulampa ->
Depok di alur Ciliwung (`ruas_km`) + jarak Depok ke kecamatan. Butuh shapely (tidak dipasang di grup dashboard):
    cd src && uv run --group dashboard --with shapely python -m dashboard.build_wilayah
"""

import argparse
import heapq
import json
import logging
import math
import re
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests
from shapely.geometry import LineString, MultiPolygon, Point, box, mapping
from shapely.ops import linemerge, polygonize, unary_union
from shapely.prepared import prep

from logging_setup import configure_logging
from settings import load_config

logger = logging.getLogger(__name__)

OUT = Path(__file__).parent
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "flood-forecasting-pipeline/0.1 (thesis research)"  # kebijakan Overpass: identitas yang jelas
BUFFER_M = 300  # dari validasi: recall 55/60 kelurahan BPBD, lihat README
DEG = 1 / 110_500  # meter -> derajat di lintang Jakarta (cukup untuk buffer ratusan meter)
SIMPLIFY = 0.0002  # ~20 m
# Bingkai peta: DKI daratan plus pos hulu di Ciledug (barat) dan Depok (selatan); Katulampa di luar,
# ditaruh di tepi bawah oleh figures.map_figure.
PETA = box(106.665, -6.41, 106.98, -6.08)

# Pola nama way OSM per sungai (huruf kecil). OSM menulis "Ci Liwung", "Kali Krukut", "Sunter River", ...
SUNGAI = {
    "Ciliwung": r"^(kali |sungai )?ci ?liwung$",
    "Krukut": r"^(kali |sungai )?krukut$",
    "Pesanggrahan": r"^(kali )?pesanggrahan$|^cengkareng drain$",
    "Angke": r"^(kali )?angke$|^cengkareng drain$",
    "Cipinang": r"^(kali )?ci ?pinang$",
    "Sunter": r"^(kali )?sunter( river)?$",
}
# Batas hilir (lintang) = pintu air tujuan menurut SOP; posisi dari node OSM Pintu Air Manggarai
# (4819922350) dan Pintu Air Karet (4849205566).
SAMPAI = {"Ciliwung": ("PA Manggarai", -6.2078), "Krukut": ("PA Karet", -6.1981),
          "Pesanggrahan": ("laut, lewat Cengkareng Drain", None), "Angke": ("laut", None),
          "Cipinang": ("PA Pulo Gadung", None), "Sunter": ("laut", None)}
# Kali Sunter di Cempaka Putih/Kemayoran bermuara ke Sunter di Danau Sunter, tapi bukan alur dari Pos Sunter Hulu.
BUANG = {"Sunter": box(106.80, -6.20, 106.875, -6.10)}
POS = {"Bendung Katulampa": "Ciliwung", "Pos Depok": "Ciliwung", "Pos Krukut Hulu": "Krukut",
       "Pos Pesanggrahan": "Pesanggrahan", "Pos Angke Hulu": "Angke", "Pos Cipinang Hulu": "Cipinang",
       "Pos Sunter Hulu": "Sunter", "Waduk Pluit": "Waduk Pluit"}

# Pos di luar bingkai Q_AIR: jarak ke kecamatan lewat pos hilirnya di alur yang sama (Q_HULU).
LEWAT = {"Bendung Katulampa": "Pos Depok"}
KORIDOR_M = 30  # ruas air OSM dalam sekian meter dari alur pos ikut graf jarak

# Kelurahan yang disebut BPBD DKI dalam peringatan dini per pos, dikutip media (untuk validasi saja).
REFERENSI = {
    "Ciliwung": ("Srengseng Sawah, Pejaten Timur, Rawajati, Balekambang, Pengadegan, Cikoko, Cawang, Kebon Baru, "
                 "Bukit Duri, Bidara Cina, Kampung Melayu, Kalibata",
                 "detik.com 11-10-2022 (d-6342287); kontan.co.id 24-02-2014 (Katulampa Siaga III)"),
    "Angke": ("Rawa Buaya, Cengkareng Timur, Cengkareng Barat, Kembangan Utara, Kedoya Utara, Kapuk, Duri Kosambi, "
              "Kedaung Kali Angke", "inews.id 06-02-2021; republika.co.id 05-02-2021 (qo1gfh330)"),
    "Pesanggrahan": ("Lebak Bulus, Pondok Pinang, Bintaro, Pesanggrahan, Cipulir, Ulujami, Sukabumi Selatan, "
                     "Kebon Jeruk, Kedoya Utara, Kedoya Selatan, Rawa Buaya, Kembangan Utara, Kembangan Selatan, "
                     "Cengkareng Timur, Srengseng, Kelapa Dua, Kapuk, Kedaung Kali Angke, Kapuk Muara",
                     "medcom.id 31-12-2023 (xkEoYxDN)"),
    "Sunter": ("Bambu Apus, Cilangkap, Pondok Ranggon, Setu, Lubang Buaya, Pondok Bambu, Pondok Kelapa, Cipinang, "
               "Cipinang Melayu, Cipinang Muara, Duren Sawit, Jatinegara Kaum, Kayu Putih, Pulo Gadung, Sumur Batu, "
               "Kelapa Gading Barat, Kelapa Gading Timur, Kebon Bawang, Rawa Badak Selatan, Rawa Badak Utara, "
               "Sungai Bambu", "medcom.id 03-12-2022 (4KZP3Yqb)"),
}

Q_ADMIN = """[out:json][timeout:180];
area["boundary"="administrative"]["admin_level"="4"]["name"~"Jakarta"]->.jkt;
rel(area.jkt)["boundary"="administrative"]["admin_level"~"^(5|6|7)$"];
out geom;"""
Q_KONTEKS = """[out:json][timeout:180];
rel["boundary"="administrative"]["admin_level"="5"]["name"~"^(Kota )?(Depok|Tangerang|Tangerang Selatan)$"]
  (-6.6,106.4,-6.0,107.1);
out geom;"""
Q_AIR = """[out:json][timeout:240][bbox:-6.42,106.66,-6.08,107.0];
(way["waterway"~"^(river|canal)$"];
 way["waterway"~"^(stream|drain|ditch)$"]["name"];
 way["natural"="water"]["name"="Waduk Pluit"];);
out geom;"""

Q_HULU = """[out:json][timeout:180][bbox:-6.66,106.76,-6.38,106.90];
way["waterway"="river"]["name"~"^(kali |sungai )?ci ?liwung$",i];
out geom;"""


def overpass(query):
    for attempt in range(3):
        r = requests.post(OVERPASS, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=300)
        if r.status_code == 200:
            return r.json()["elements"]
        logger.warning("Overpass %s, coba lagi: %s", r.status_code, r.text[:200])
        time.sleep(30 * (attempt + 1))
    r.raise_for_status()


def _polygon(rel):
    """Relation batas administrasi OSM -> (Multi)Polygon: ring luar dikurangi ring dalam."""
    def rings(role):
        lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in rel["members"]
                 if m["type"] == "way" and (m.get("role") or "outer") == role and m.get("geometry")]
        return unary_union(list(polygonize(linemerge(lines)))) if lines else None
    outer, inner = rings("outer"), rings("inner")
    return outer.difference(inner) if inner is not None else outer


def wilayah(elements):
    """(kota {nama: poligon}, kecamatan [(nama, kota, poligon)], kelurahan [(nama, kecamatan, kota, poligon)])."""
    by_level = defaultdict(list)
    for e in elements:
        by_level[e["tags"]["admin_level"]].append((e["tags"]["name"], _polygon(e)))

    def parent(geom, pool):
        point = geom.representative_point()
        return next((name for name, g in pool if g.contains(point)), None)

    kota = dict(by_level["5"])
    kec = [(n, parent(g, kota.items()), g) for n, g in by_level["6"]]
    kec_kota = {n: k for n, k, _ in kec}
    kel = [(n, k, kec_kota.get(k), g) for n, g in by_level["7"] if (k := parent(g, [(n2, g2) for n2, _, g2 in kec]))]
    daratan = lambda k: k and "Seribu" not in k  # noqa: E731
    return kota, [x for x in kec if daratan(x[1])], [x for x in kel if daratan(x[2])]


def alur(elements, pattern):
    """Way bernama sungai ini, disambung lewat ruas tanpa nama searah aliran (arah way OSM = arah aliran)."""
    ways = {e["id"]: e for e in elements if e["type"] == "way" and e["tags"].get("waterway")}
    starts, ends, inner = defaultdict(list), defaultdict(list), defaultdict(list)
    for i, w in ways.items():
        starts[w["nodes"][0]].append(i)
        ends[w["nodes"][-1]].append(i)
        for n in w["nodes"][1:-1]:
            inner[n].append(i)
    name = lambda i: (ways[i]["tags"].get("name") or "").lower()  # noqa: E731
    seed = {i for i in ways if name(i) and re.match(pattern, name(i))}
    out, todo = set(seed), list(seed)
    while todo:  # hilir: lanjut ke ruas tanpa nama atau bernama sama, juga yang disambung di tengah way
        last = ways[todo.pop()]["nodes"][-1]
        for n in starts[last] + inner[last]:
            if n not in out and (not name(n) or re.match(pattern, name(n))):
                out.add(n)
                todo.append(n)
    line = lambda i: LineString([(p["lon"], p["lat"]) for p in ways[i]["geometry"]])  # noqa: E731

    def upstream_len(i, depth=0):
        preds = [p for p in ends[ways[i]["nodes"][0]] if not name(p)] if depth < 60 else []
        return line(i).length + max([upstream_len(p, depth + 1) for p in preds] or [0])

    for head in [i for i in out if not any(p in out for p in ends[ways[i]["nodes"][0]])]:
        cur = head  # hulu: ruas tanpa nama terpanjang, sampai bertemu ruas bernama
        for _ in range(100):
            preds = [p for p in ends[ways[cur]["nodes"][0]] if not name(p) and p not in out]
            if not preds:
                break
            cur = max(preds, key=upstream_len)
            out.add(cur)
    return unary_union([line(i) for i in out])


def hulu(elements, start, target):
    """Alur dari titik pos (lon, lat) ke `target`, menyusuri way air OSM searah aliran (Dijkstra).

    Mulai dari node air terdekat (maks 500 m) yang jalur hilirnya sampai ke `target`; None kalau tidak ada.
    """
    coords, edges = {}, defaultdict(list)
    for e in elements:
        if e["type"] != "way" or not e["tags"].get("waterway"):
            continue
        for a, b, pa, pb in zip(e["nodes"], e["nodes"][1:], e["geometry"], e["geometry"][1:]):
            coords[a], coords[b] = (pa["lon"], pa["lat"]), (pb["lon"], pb["lat"])
            edges[a].append((b, math.dist(coords[a], coords[b])))
    near, here = target.buffer(20 * DEG), Point(start)
    for s in sorted(coords, key=lambda n: here.distance(Point(coords[n])))[:20]:
        if here.distance(Point(coords[s])) > 500 * DEG:
            break
        prev, dist, todo = {s: None}, {s: 0.0}, [(0.0, s)]
        while todo:
            d, n = heapq.heappop(todo)
            if near.contains(Point(coords[n])):
                path = []
                while n is not None:
                    path.append(coords[n])
                    n = prev[n]
                return LineString([start, *reversed(path)])
            if d > dist[n]:
                continue
            for m, w in edges[n]:
                if d + w < dist.get(m, math.inf):
                    dist[m], prev[m] = d + w, n
                    heapq.heappush(todo, (d + w, m))
    return None


def graf_air(elements, area=None):
    """Graf TAK BERARAH node way air OSM: ({node: (lon, lat)}, {node: [(tetangga, meter)]}).

    `area` = hanya ruas yang kedua ujungnya di dalamnya. Tak berarah karena arah way OSM tidak selalu searah
    aliran; arah hilir sudah dijaga koridornya (alur pos mulai dari lintang pos ke utara).
    """
    area = prep(area) if area is not None else None
    coords, edges = {}, defaultdict(list)
    for e in elements:
        if e["type"] != "way" or not e["tags"].get("waterway"):
            continue
        for a, b, pa, pb in zip(e["nodes"], e["nodes"][1:], e["geometry"], e["geometry"][1:]):
            ca, cb = (pa["lon"], pa["lat"]), (pb["lon"], pb["lat"])
            if area is not None and not (area.contains(Point(ca)) and area.contains(Point(cb))):
                continue
            coords[a], coords[b] = ca, cb
            w = math.dist(ca, cb) / DEG
            edges[a].append((b, w))
            edges[b].append((a, w))
    return coords, edges


def sambung(coords, edges):
    """Sambung komponen graf yang terputus lewat celah terdekat (garis lurus), seperti MST antarkomponen.

    Way OSM kadang tidak berbagi node (Krukut: celah 34 m), dan potongan alur bisa terpisah dari alur utama
    (Angke hilir). Garis lurus memendekkan jarak: waktu tempuh terbaca lebih cepat, arah yang aman untuk
    peringatan. Mengembalikan panjang tiap jembatan (m).
    """
    comp = {}
    for n in coords:
        if n in comp:
            continue
        comp[n], stack = n, [n]
        while stack:
            for m, _ in edges[stack.pop()]:
                if m not in comp:
                    comp[m] = n
                    stack.append(m)
    groups = defaultdict(list)
    for n, c in comp.items():
        groups[c].append(n)
    groups = sorted(groups.values(), key=len, reverse=True)
    joined, rest, bridges = list(groups[0]) if groups else [], groups[1:], []
    while rest:  # Prim: komponen terdekat ke yang sudah tersambung
        best = min(((min((math.dist(coords[a], coords[b]), a, b) for a in joined for b in g), i)
                    for i, g in enumerate(rest)), key=lambda x: x[0][0])
        (d, a, b), i = best
        edges[a].append((b, d / DEG))
        edges[b].append((a, d / DEG))
        bridges.append(round(d / DEG))
        joined += rest.pop(i)
    return bridges


def jarak_alur(coords, edges, start):
    """{node: meter sepanjang alur dari titik `start` (lon, lat)}, mulai dari node graf terdekat."""
    here = Point(start)
    s = min(coords, key=lambda n: here.distance(Point(coords[n])))
    dist = {s: here.distance(Point(coords[s])) / DEG}
    todo = [(dist[s], s)]
    while todo:
        d, n = heapq.heappop(todo)
        if d > dist[n]:
            continue
        for m, w in edges[n]:
            if d + w < dist.get(m, math.inf):
                dist[m] = d + w
                heapq.heappush(todo, (d + w, m))
    return dist


def kecamatan_km(dist, coords, kec_geoms, names):
    """{kecamatan: km dari pos ke node alur pertama dalam BUFFER_M dari kecamatan}; None kalau tak terjangkau."""
    out = {}
    for name in names:
        zone = prep(kec_geoms[name].buffer(BUFFER_M * DEG))
        near = [d for n, d in dist.items() if zone.contains(Point(coords[n]))]
        out[name] = round(min(near) / 1000, 1) if near else None
    return out


def _norm(name):
    return re.sub(r"[^a-z]", "", name.lower()).replace("ranggon", "rangon")


def _hilir(area, kel):
    """Kelurahan yang terkena `area` (minimal 50 x 50 m), urut dari selatan (hulu) ke utara."""
    hit = [(n, k, kota, g) for n, k, kota, g in kel if g.intersection(area).area > (50 * DEG) ** 2]
    return [[n, k, kota] for n, k, kota, g in sorted(hit, key=lambda x: x[3].representative_point().y)]


def _rounded(geom, digits=5):
    def walk(c):
        return [walk(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], digits), round(c[1], digits)]
    g = mapping(geom)
    return {"type": g["type"], "coordinates": walk(g["coordinates"])}


def _multi(geom):
    """Poligon -> MultiPolygon yang dibulatkan, bentuk yang dibaca figures._rings."""
    return _rounded(MultiPolygon([p for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon"]))


def build():
    _, kec, kel = wilayah(overpass(Q_ADMIN))
    logger.info("%d kecamatan dan %d kelurahan DKI daratan", len(kec), len(kel))
    konteks = {re.sub(r"^Kota ", "", e["tags"]["name"]): _polygon(e) for e in overpass(Q_KONTEKS)}
    logger.info("Wilayah konteks: %s", ", ".join(konteks))
    air = overpass(Q_AIR)
    daratan = unary_union([g for *_, g in kel])

    sungai, utuh = {}, {}
    for nama, pattern in SUNGAI.items():
        utuh[nama] = alur(air, pattern)  # untuk graf jarak: meander yang keluar DKI tetap menyambung
        geom = utuh[nama].intersection(daratan)
        cut = SAMPAI[nama][1]
        if cut is not None:
            geom = geom.intersection(box(100, -90, 120, cut))
        if nama in BUANG:
            geom = geom.difference(BUANG[nama])
        # potongan bisa menyisakan titik (GeometryCollection): simpan garisnya saja
        sungai[nama] = linemerge([p for part in getattr(geom, "geoms", [geom])
                                  for p in getattr(part, "geoms", [part]) if isinstance(p, LineString)])
        logger.info("%s: %.1f km di DKI", nama, geom.length / DEG / 1000)
    pluit = unary_union([LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in air
                         if e["tags"].get("name") == "Waduk Pluit"])
    stations = load_config("dashboard")["stations"]
    alur_hulu, area, koridor = {}, {}, {}
    for pos, nama in POS.items():
        if nama == "Waduk Pluit":
            area[pos] = unary_union(list(polygonize(pluit))).buffer(BUFFER_M * DEG)
            continue
        s = stations.get(pos, {})
        line = None
        if "lat" in s and PETA.contains(Point(s["lon"], s["lat"])):  # Katulampa di luar peta: tanpa alur hulu
            line = hulu(air, (s["lon"], s["lat"]), sungai[nama])
            if line is None:
                logger.warning("%s: alur hulu ke %s tidak ketemu", pos, nama)
            else:
                alur_hulu[pos] = line
                logger.info("%s: alur hulu %.1f km", pos, line.length / DEG / 1000)
        # sungai di sini mengalir ke utara: alur DKI di selatan pos (hulunya) tidak ikut
        mulai = s["lat"] if line is not None else -90
        jalur = unary_union([sungai[nama], *([line] if line is not None else [])]).intersection(daratan)
        area[pos] = jalur.intersection(box(100, mulai, 120, SAMPAI[nama][1] or 0)).buffer(BUFFER_M * DEG)
        if line is not None:
            koridor[pos] = (unary_union([utuh[nama], line]).intersection(box(100, s["lat"] - 50 * DEG, 120,
                                                                              SAMPAI[nama][1] or 0))
                            .buffer(KORIDOR_M * DEG))

    kec_geoms = {n: g for n, _, g in kec}
    hilir_kel = {pos: _hilir(area[pos], kel) for pos in POS}
    jarak, ruas = {}, {}
    for pos in koridor:
        names = list(dict.fromkeys(k for _, k, _ in hilir_kel[pos]))
        coords, edges = graf_air(air, koridor[pos])
        bridges = sambung(coords, edges)
        if any(b > 100 for b in bridges):
            logger.warning("%s: alur disambung lewat celah garis lurus %s m", pos, [b for b in bridges if b > 100])
        jarak[pos] = kecamatan_km(jarak_alur(coords, edges, (stations[pos]["lon"], stations[pos]["lat"])),
                                  coords, kec_geoms, names)
        logger.info("%s: jarak ke kecamatan hilir %s", pos, jarak[pos])
        if None in jarak[pos].values():
            logger.warning("%s: alur tidak sampai ke %s", pos, [k for k, v in jarak[pos].items() if v is None])
    for pos, via in LEWAT.items():
        coords, edges = graf_air(overpass(Q_HULU))
        bridges = sambung(coords, edges)
        if any(b > 100 for b in bridges):
            logger.warning("%s -> %s: alur disambung lewat celah garis lurus %s m", pos, via, [b for b in bridges if b > 100])
        dist = jarak_alur(coords, edges, (stations[pos]["lon"], stations[pos]["lat"]))
        target = Point(stations[via]["lon"], stations[via]["lat"])
        node = min(dist, key=lambda n: target.distance(Point(coords[n])))
        ruas[pos] = {via: round(dist[node] / 1000, 1)}
        logger.info("%s -> %s: %.1f km di alur (node %.0f m dari titik pos)", pos, via, ruas[pos][via],
                    target.distance(Point(coords[node])) / DEG)
        jarak[pos] = {k: (None if jarak[via].get(k) is None else round(ruas[pos][via] + jarak[via][k], 1))
                      for k in dict.fromkeys(k for _, k, _ in hilir_kel[pos])}

    pos_sungai = {nama: pos for pos, nama in POS.items()}  # pos paling hilir per sungai (Ciliwung: Depok)
    for nama, (names, _) in REFERENSI.items():
        ref = {_norm(x) for x in names.split(", ")}
        got = {_norm(n) for n, *_ in hilir_kel[pos_sungai[nama]]}
        logger.info("Validasi %s: %d/%d kelurahan BPBD tercakup, meleset: %s", nama, len(ref & got), len(ref),
                    ", ".join(sorted(ref - got)) or "-")

    kota = defaultdict(list)
    for _, k, g in kec:
        kota[k].append(g)
    dki = unary_union([g for _, _, g in kec])
    kota_geoms = [(k, unary_union(kota[k])) for k in ("Jakarta Utara", "Jakarta Barat", "Jakarta Pusat",
                                                      "Jakarta Selatan", "Jakarta Timur")]
    kota_geoms += [(k, konteks[k].intersection(PETA).difference(dki)) for k in ("Depok", "Tangerang",
                                                                                "Tangerang Selatan")]
    kota_features = [{"type": "Feature", "properties": {"name": k},
                      "geometry": _multi(g.simplify(SIMPLIFY, preserve_topology=True))} for k, g in kota_geoms]
    kec_features = [{"type": "Feature", "properties": {"name": n, "kota": k}, "geometry": _multi(s)}
                    for n, k, g in sorted(kec, key=lambda x: (x[1], x[0]))
                    if not (s := g.simplify(SIMPLIFY, preserve_topology=True)).is_empty]
    sungai_features = [{"type": "Feature", "properties": {"name": nama},
                        "geometry": _rounded(g.simplify(SIMPLIFY / 2))} for nama, g in [*sungai.items(),
                                                                                         ("Waduk Pluit", pluit)]]
    sungai_features += [{"type": "Feature", "properties": {"name": POS[pos], "pos": pos},
                         "geometry": _rounded(g.simplify(SIMPLIFY / 2))} for pos, g in alur_hulu.items()]
    hilir = {
        "sumber": "© OpenStreetMap contributors (ODbL 1.0) lewat Overpass API; diturunkan oleh "
                  "src/dashboard/build_wilayah.py, bukan daftar resmi BPBD",
        "dibuat": date.today().isoformat(), "buffer_m": BUFFER_M, "ruas_km": ruas,
        "pos": {pos: {"sungai": nama, "sampai": SAMPAI.get(nama, ("waduk dan sekitarnya", None))[0],
                      "kelurahan": hilir_kel[pos], **({"kecamatan_km": jarak[pos]} if pos in jarak else {})}
                for pos, nama in POS.items()},
    }
    for name, content, indent in (("kota.geojson", {"type": "FeatureCollection", "features": kota_features}, None),
                                  ("kecamatan.geojson", {"type": "FeatureCollection", "features": kec_features}, None),
                                  ("sungai.geojson", {"type": "FeatureCollection", "features": sungai_features}, None),
                                  ("hilir.json", hilir, 1)):  # hilir.json dibaca orang: satu kelurahan per baris
        text = json.dumps(content, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
        (OUT / name).write_text(text + "\n", encoding="utf-8")
        logger.info("Tulis %s", OUT / name)


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    configure_logging()
    build()


if __name__ == "__main__":
    main()
