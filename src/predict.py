"""CLI untuk pipeline prediksi end-to-end (raw BigQuery -> forecast cm).

Menggunakan model terbaik menurut tabel `model_selection` dan data
`station_features` paling baru.

Pemakaian:
    python predict.py
    python predict.py --station "Bendung Katulampa"
    python predict.py --horizon 1 3
    python predict.py --write-bq
    python predict.py --csv forecast.csv
"""

import argparse

from prediction import forecast_latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", default=None, help="Filter satu stasiun saja.")
    parser.add_argument("--horizon", type=int, nargs="+", default=None,
                         help="Filter horizon (jam), mis. --horizon 1 3.")
    parser.add_argument("--write-bq", action="store_true",
                         help="Simpan hasil ke BigQuery (tables.forecast_output).")
    parser.add_argument("--csv", default=None, help="Simpan hasil ke file CSV.")
    args = parser.parse_args()

    forecast_df, model_name = forecast_latest(
        station=args.station, horizons=args.horizon, write_bq=args.write_bq,
    )

    print(f"\nForecast ('{model_name}'):")
    print(forecast_df.to_string(index=False))

    if args.csv:
        forecast_df.to_csv(args.csv, index=False)
        print(f"\nDisimpan ke {args.csv}")


if __name__ == "__main__":
    main()
