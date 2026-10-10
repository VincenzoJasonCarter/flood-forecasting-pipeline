"""Pemilihan sel hujan per stasiun lewat korelasi silang hujan vs kenaikan TMA.

Untuk tiap (stasiun, sel): korelasi antara hujan di sel itu (dijumlah
`smooth_hours` jam) yang digeser `lag` jam dengan kenaikan muka air per jam,
untuk lag 0..`max_lag`. Lag dengan korelasi tertinggi memperkirakan waktu
tempuh hujan di sel itu sampai ke stasiun.

Hanya dihitung di periode train (TRAIN_RATIO pertama), supaya pemilihan sel
tidak "mengintip" periode val/test yang dipakai evaluasi model.

Pemakaian (dari src/, butuh parquet hourly TMA + hasil `python -m rainfall --survey`):
    python -m rainfall.analysis
    python -m rainfall.analysis --stations "Bendung Katulampa" "Pos Depok" --max-lag 36
"""

import argparse
from pathlib import Path

import pandas as pd

from preprocessing.splitting import split_data
from raw_preprocessing.config import CALENDAR_COLS, default_output_path

from .config import RANKING_PATH, SURVEY_OUTPUT_PATH
from .frames import parse_cell_column


def level_rise(level):
    """Kenaikan muka air per jam; penurunan dianggap 0 (hujan hanya menaikkan)."""
    return level.diff().clip(lower=0)


def lagged_correlation(rain, rise, max_lag=24, smooth_hours=3):
    """Korelasi Pearson hujan (jumlah `smooth_hours` jam, digeser `lag` jam)
    dengan kenaikan TMA, untuk lag 0..max_lag. Index = lag (jam)."""
    smoothed = rain.rolling(smooth_hours, min_periods=1).sum()
    return pd.Series({lag: smoothed.shift(lag).corr(rise) for lag in range(max_lag + 1)}, name="corr")


def rank_cells(rain_df, level, max_lag=24, smooth_hours=3):
    """Ranking sel untuk satu stasiun: lag terbaik dan korelasinya, terurut menurun."""
    rise = level_rise(level)
    rain_df, rise = rain_df.align(rise, join="inner", axis=0)
    rows = []
    for col in rain_df.columns:
        corr = lagged_correlation(rain_df[col], rise, max_lag, smooth_hours).dropna()
        lat, lon = parse_cell_column(col)
        rows.append({
            "cell": col, "lat": lat, "lon": lon,
            "best_lag_h": int(corr.idxmax()) if len(corr) else None,
            "corr": float(corr.max()) if len(corr) else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("corr", ascending=False, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stations", nargs="+", default=None, help="Default: semua stasiun.")
    parser.add_argument("--max-lag", type=int, default=24, help="Lag maksimum (jam), default 24.")
    parser.add_argument("--smooth", type=int, default=3, help="Jendela jumlah hujan (jam), default 3.")
    parser.add_argument("--top", type=int, default=5, help="Jumlah sel teratas yang dicetak per stasiun.")
    parser.add_argument("--features", type=Path, default=default_output_path("hourly"),
                        help="Parquet station_features_hourly (output raw_preprocessing).")
    parser.add_argument("--rainfall", type=Path, default=SURVEY_OUTPUT_PATH,
                        help=f"Parquet hujan semua sel (default: hasil --survey, {SURVEY_OUTPUT_PATH.name}).")
    parser.add_argument("--output", type=Path, default=RANKING_PATH)
    args = parser.parse_args()

    features = pd.read_parquet(args.features)
    rain = pd.read_parquet(args.rainfall)
    train, _, _ = split_data(features)
    overlap = rain.index[(rain.index >= train.index[0]) & (rain.index <= train.index[-1])]
    print(f"Periode train: {train.index[0]} -> {train.index[-1]} | {rain.shape[1]} sel hujan | "
          f"{len(overlap):,} jam hujan di dalam periode train")
    if len(overlap) == 0:
        raise SystemExit("Data hujan tidak beririsan dengan periode train; cek tanggal survey di config/rainfall.yaml.")

    stations = args.stations or [c for c in features.columns if c not in CALENDAR_COLS]
    results = []
    for station in stations:
        ranking = rank_cells(rain, train[station], args.max_lag, args.smooth)
        ranking.insert(0, "station", station)
        results.append(ranking)
        print(f"\n{station}:")
        print(ranking.head(args.top).drop(columns="station").round(3).to_string(index=False))

    pd.concat(results, ignore_index=True).to_csv(args.output, index=False)
    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
