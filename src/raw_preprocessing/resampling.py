"""Hourly resampling, long -> wide restructuring, and daily aggregation."""

from .config import DAILY_FREQ, RESAMPLE_FREQ


def resample_hourly(df):
    """Rata-rata water_level per jam per stasiun. Return long frame
    [station_name, datetime, water_level]; jam tanpa observasi menjadi NaN."""
    return (df
            .set_index("datetime")
            .groupby("station_name")["water_level"]
            .resample(RESAMPLE_FREQ)
            .mean()
            .reset_index())


def to_wide(df_long, value_col="water_level"):
    """Pivot long -> wide (satu kolom per stasiun) di grid per jam yang kontinu."""
    df_wide = (df_long
               .drop_duplicates(subset=["datetime", "station_name"])
               .pivot(index="datetime", columns="station_name", values=value_col)
               .sort_index())
    return df_wide.asfreq(RESAMPLE_FREQ)


def to_daily_max(df_wide):
    """Puncak (max) water level per hari per stasiun dari grid per jam.
    Hari tanpa satu pun nilai valid menjadi NaN."""
    return df_wide.resample(DAILY_FREQ).max()
