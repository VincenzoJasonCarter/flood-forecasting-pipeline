"""NaN imputation using per-station hourly medians from the training set."""

import pandas as pd


def compute_hourly_medians(df_train_raw, station_cols):
    """Hitung hourly median per stasiun dari training set (raw cm)."""
    return {
        station: df_train_raw[station].groupby(df_train_raw.index.hour).median()
        for station in station_cols
    }


def fill_nan_hourly_median(df, hourly_medians, station_cols):
    df = df.copy()
    for station in station_cols:
        nan_mask = df[station].isna()
        if nan_mask.sum() == 0:
            continue
        df.loc[nan_mask, station] = df.loc[nan_mask].index.hour.map(hourly_medians[station])
        print(f"  [{station}] filled {nan_mask.sum()} NaN")
    return df


def medians_to_json(hourly_medians):
    """{station: Series(jam -> median)} -> dict JSON-able (kunci jam string),
    disimpan di metadata supaya serving memakai median yang sama persis."""
    return {station: {str(int(hour)): float(value) for hour, value in med.items()}
            for station, med in hourly_medians.items()}


def medians_from_json(payload):
    return {station: pd.Series({int(hour): value for hour, value in med.items()}, dtype="float64")
            for station, med in payload.items()}
