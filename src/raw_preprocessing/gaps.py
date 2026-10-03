"""Gap analysis and limited gap filling on the wide hourly frame."""

from .config import GAP_LIMIT


def gap_lengths(series):
    """Panjang setiap run NaN berturut-turut (dalam timestep/jam)."""
    is_na = series.isna()
    # Setiap NaN dikelompokkan ke nilai valid terakhir sebelumnya, jadi satu
    # grup = satu run NaN (run di awal series masuk grup 0).
    runs = is_na.groupby((~is_na).cumsum()).sum()
    return [int(n) for n in runs if n > 0]


def fill_gaps(df_wide, limit=GAP_LIMIT):
    """Interpolasi berbasis waktu, lalu ffill, lalu bfill — masing-masing
    maksimal `limit` NaN berturut-turut.

    `limit` di pandas mengisi `limit` NaN pertama dari setiap gap, termasuk
    gap yang lebih panjang dari `limit`; gap panjang jadi terisi sebagian
    dari kedua ujungnya, sisanya tetap NaN.
    """
    df_filled = df_wide.interpolate(method="time", limit=limit)
    df_filled = df_filled.ffill(limit=limit)
    # bfill terutama untuk NaN di awal series.
    return df_filled.bfill(limit=limit)
