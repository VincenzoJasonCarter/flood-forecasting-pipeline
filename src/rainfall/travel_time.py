"""Waktu tempuh gelombang banjir antara dua pos di alur yang sama (default Katulampa -> Depok).

Dua estimasi per kejadian, keduanya dari TMA per jam:
    puncak   : jam puncak pos hilir - jam puncak pos hulu
    naik-50% : jam pos hilir melewati 50% kenaikannya - jam pos hulu melewati 50% kenaikannya
               (lebih tahan terhadap puncak datar akibat resolusi sensor 10 cm). Kenaikan diukur dari
               titik terendah sebelum puncak, jadi sisa banjir sebelumnya tidak terbaca sebagai kenaikan.

Kejadian = pos hulu di atas `--threshold` (default batas Siaga 3 pos hulu di config/dashboard.yaml);
kejadian yang mulai kurang dari `--gap` jam setelah kejadian sebelumnya berakhir DIGABUNG (gelombang
kedua sering lebih tinggi). Puncak hulu = maksimum selama kejadian; puncak hilir dicari di
[puncak hulu - 2 j, puncak hulu + `--window` j]. Jendela sengaja pendek: lag Katulampa -> Depok ~4 jam,
jendela lebar menangkap puncak hilir dari gelombang hulu berikutnya. Kejadian dibuang (dan dihitung) kalau:
    - kenaikan di hilir < `--min-rise` cm (gelombang tidak terlihat di hilir),
    - puncak hilir 1-2 jam sebelum puncak hulu (kenaikan hilir dari hujan lokal, bukan kiriman), atau
    - ada NaN di jendela kejadian.

Pembanding: lag korelasi silang kenaikan TMA per jam (fungsi yang sama dengan rainfall.analysis).
Hasilnya dipakai laporan dashboard (config/dashboard.yaml `laporan.tempuh`) untuk kecepatan rambat
gelombang dari pos ke kecamatan hilir.

Pemakaian (dari src/, butuh parquet hourly hasil raw_preprocessing; `make travel-time`):
    python -m rainfall.travel_time
    python -m rainfall.travel_time --threshold 150   # hanya kejadian di atas Siaga 2 Katulampa
"""

import argparse
import logging
from pathlib import Path

import pandas as pd

from logging_setup import configure_logging
from raw_preprocessing.config import default_output_path
from settings import CONFIG_DIR, load_config

from .analysis import lagged_correlation, level_rise

logger = logging.getLogger(__name__)

OUTPUT_PATH = CONFIG_DIR.parent / "artifacts" / "travel_time_events.csv"
HOUR = pd.Timedelta(hours=1)


def find_events(up, threshold, gap):
    """[(mulai, akhir)] rentang `up` > threshold; rentang yang berjarak < gap jam digabung."""
    above = up > threshold
    starts = up.index[above & ~above.shift(1, fill_value=False)]
    ends = up.index[above & ~above.shift(-1, fill_value=False)]
    events = []
    for start, end in zip(starts, ends):
        if events and start - events[-1][1] < gap * HOUR:
            events[-1] = (events[-1][0], end)
        else:
            events.append((start, end))
    return events


def half_rise_time(s):
    """Jam pertama `s` melewati 50% kenaikan menuju puncaknya; `s` berakhir tepat di puncak.

    Puncak = titik terakhir, bukan idxmax: sisa banjir sebelumnya di awal seri bisa lebih tinggi. Kenaikan
    diukur dari lembah terakhir sebelum puncak (mundur selama TMA tidak naik), bukan dari titik terendah
    seluruh seri: di kejadian bergelombang, titik terendah ada sebelum gelombang pertama.
    """
    i = len(s) - 1
    while i > 0 and s.iloc[i - 1] <= s.iloc[i]:
        i -= 1
    rising = s.iloc[i:]
    level = rising.iloc[0] + 0.5 * (rising.iloc[-1] - rising.iloc[0])
    return rising[rising >= level].index[0]


def event_lags(df, upstream, downstream, threshold, gap=24, window=10, min_rise=30, pre=12):
    """(DataFrame satu baris per kejadian, {alasan: jumlah kejadian yang dibuang})."""
    rows, dropped = [], {"hilir_tidak_naik": 0, "hilir_lebih_dulu": 0, "nan": 0}
    for start, end in find_events(df[upstream], threshold, gap):
        span = df.loc[start - pre * HOUR: end + window * HOUR]
        if span[[upstream, downstream]].isna().any().any():
            dropped["nan"] += 1
            continue
        t_up = span[upstream].loc[start:end].idxmax()
        dn = span[downstream].loc[t_up - 2 * HOUR: t_up + window * HOUR]
        dn_base = span[downstream].loc[:start].min()
        if dn.max() - dn_base < min_rise:
            dropped["hilir_tidak_naik"] += 1
            continue
        t_dn = dn.idxmax()
        if t_dn < t_up:
            dropped["hilir_lebih_dulu"] += 1
            continue
        h_up = half_rise_time(span[upstream].loc[:t_up])
        h_dn = half_rise_time(span[downstream].loc[:t_dn])
        rows.append({
            "mulai": start, "puncak_hulu": t_up, "tma_hulu": span.at[t_up, upstream],
            "puncak_hilir": t_dn, "tma_hilir": span.at[t_dn, downstream],
            "lag_puncak_j": (t_dn - t_up) / HOUR, "lag_naik50_j": (h_dn - h_up) / HOUR,
        })
    return pd.DataFrame(rows), dropped


def summarize(values):
    """{median, q1, q3, min, max} sebuah kolom lag (jam)."""
    return {"median": values.median(), "q1": values.quantile(0.25), "q3": values.quantile(0.75),
            "min": values.min(), "max": values.max()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--upstream", default="Bendung Katulampa")
    p.add_argument("--downstream", default="Pos Depok")
    p.add_argument("--threshold", type=float, help="cm; kejadian = hulu > nilai ini. Default: Siaga 3 pos hulu.")
    p.add_argument("--gap", type=int, default=24, help="jam; kejadian yang lebih dekat dari ini digabung.")
    p.add_argument("--window", type=int, default=10, help="jam setelah puncak hulu untuk mencari puncak hilir.")
    p.add_argument("--min-rise", type=float, default=30, help="cm; kenaikan minimum di hilir agar kejadian dihitung.")
    p.add_argument("--max-lag", type=int, default=18, help="jam; lag terjauh korelasi silang.")
    p.add_argument("--features", type=Path, default=default_output_path("hourly"))
    p.add_argument("--output", type=Path, default=OUTPUT_PATH)
    a = p.parse_args()
    configure_logging()

    threshold = a.threshold
    if threshold is None:
        threshold = load_config("dashboard")["stations"][a.upstream]["siaga"][3]
    df = pd.read_parquet(a.features)[[a.upstream, a.downstream]].sort_index()
    events, dropped = event_lags(df, a.upstream, a.downstream, threshold, a.gap, a.window, a.min_rise)

    logger.info("%s -> %s | kejadian hulu > %g cm: %d, dipakai %d, dibuang %s", a.upstream, a.downstream,
                threshold, len(events) + sum(dropped.values()), len(events), dropped)
    if len(events):
        for col in ("lag_puncak_j", "lag_naik50_j"):
            s = summarize(events[col])
            logger.info("  %-13s median %.1f j | IQR %.1f-%.1f j | min-maks %.0f-%.0f j",
                        col, s["median"], s["q1"], s["q3"], s["min"], s["max"])
        a.output.parent.mkdir(parents=True, exist_ok=True)
        events.to_csv(a.output, index=False)
        logger.info("  per kejadian: %s", a.output)

    # lagged_correlation menggeser seri pertama: lag k = kenaikan hulu di t-k vs kenaikan hilir di t
    corr = lagged_correlation(level_rise(df[a.upstream]), level_rise(df[a.downstream]),
                              max_lag=a.max_lag, smooth_hours=1)
    logger.info("  korelasi silang kenaikan TMA: lag terbaik %d j (r = %.2f)", int(corr.idxmax()), corr.max())


if __name__ == "__main__":
    main()
