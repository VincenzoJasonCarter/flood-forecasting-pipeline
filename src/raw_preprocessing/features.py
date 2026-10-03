"""Calendar features derived from the DatetimeIndex (hourly or daily)."""

import holidays
import pandas as pd


def add_calendar_features(df):
    df = df.copy()
    idx = df.index

    df["hour"] = idx.hour  # selalu 0 untuk index harian
    df["month"] = idx.month
    df["day_of_week"] = idx.dayofweek  # 0=Mon, 6=Sun
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)

    id_hol = holidays.Indonesia(years=idx.year.unique().tolist())
    # Cast eksplisit: isin terhadap objek datetime.date tanpa cast selalu
    # False di pandas >= 3 (di pandas 2.x hanya FutureWarning).
    holiday_dates = pd.to_datetime(list(id_hol.keys()))
    df["is_holiday"] = idx.normalize().isin(holiday_dates).astype(int)

    # Penamaan terbalik dari notebook asli: 0 = musim hujan (Nov–Apr),
    # 1 = kemarau (Mei–Okt). Dipertahankan karena model dilatih dengan encoding ini.
    df["is_rainy_season"] = (~df["month"].isin([11, 12, 1, 2, 3, 4])).astype(int)

    return df
