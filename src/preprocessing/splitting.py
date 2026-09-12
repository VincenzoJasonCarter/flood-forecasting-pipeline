"""Train/val/test splitting of the raw station feature frame."""

from .config import CALENDAR_COLS, TRAIN_RATIO, VAL_RATIO


def get_station_cols(df_fe):
    return [c for c in df_fe.columns if c not in CALENDAR_COLS]


def split_data(df_fe):
    n = len(df_fe)
    train_end_idx = int(n * TRAIN_RATIO)
    val_end_idx = int(n * (TRAIN_RATIO + VAL_RATIO))

    df_train_raw = df_fe.iloc[:train_end_idx]
    df_val_raw = df_fe.iloc[train_end_idx:val_end_idx]
    df_test_raw = df_fe.iloc[val_end_idx:]
    return df_train_raw, df_val_raw, df_test_raw
