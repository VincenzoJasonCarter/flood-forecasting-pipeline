import numpy as np
import pandas as pd

from rainfall.travel_time import event_lags, find_events, half_rise_time

IDX = pd.date_range("2024-01-01", periods=200, freq="h")


def _wave(peak_at, height, width=6.0, base=10.0):
    """Gelombang segitiga: naik `width` jam ke puncak di `peak_at`, turun `width` jam."""
    t = np.arange(len(IDX))
    return base + height * np.clip(1 - np.abs(t - peak_at) / width, 0, None)


def _pair(lag=4, peaks=(50,), heights=(100,), dn_heights=None):
    up = sum(_wave(p, h) for p, h in zip(peaks, heights)) - 10 * (len(peaks) - 1)
    dn = sum(_wave(p + lag, h, base=50.0) for p, h in zip(peaks, dn_heights or heights)) - 50 * (len(peaks) - 1)
    return pd.DataFrame({"up": up, "dn": dn}, index=IDX)


def test_find_events_merges_spells_closer_than_the_gap_instead_of_dropping_them():
    s = pd.Series(0.0, index=IDX)
    s.iloc[10:14] = 100.0   # kejadian 1
    s.iloc[20:25] = 150.0   # 6 jam kemudian: gelombang kedua, lebih tinggi
    s.iloc[80:83] = 100.0   # kejadian terpisah
    events = find_events(s, 80, gap=24)
    assert events == [(IDX[10], IDX[24]), (IDX[80], IDX[82])]


def test_half_rise_time_measures_from_the_last_trough_not_from_old_high_water():
    # sisa banjir lama (turun dari 200), lembah 50, lalu naik ke 150: 50% = 100
    s = pd.Series([200, 150, 100, 50, 50, 75, 100, 125, 150], index=IDX[:9], dtype=float)
    assert half_rise_time(s) == IDX[6]


def test_event_lags_recovers_the_true_lag_with_both_estimates():
    events, dropped = event_lags(_pair(lag=4), "up", "dn", threshold=80)
    assert len(events) == 1 and sum(dropped.values()) == 0
    assert events.loc[0, "lag_puncak_j"] == 4 and events.loc[0, "lag_naik50_j"] == 4


def test_second_upstream_wave_is_paired_with_its_own_downstream_peak():
    # dua gelombang hulu 8 jam berselang, yang kedua lebih tinggi: satu kejadian, puncak = gelombang kedua
    df = _pair(lag=4, peaks=(50, 58), heights=(80, 120))
    events, _ = event_lags(df, "up", "dn", threshold=60)
    assert len(events) == 1
    assert events.loc[0, "puncak_hulu"] == IDX[58] and events.loc[0, "lag_puncak_j"] == 4
    assert events.loc[0, "lag_naik50_j"] == 4


def test_events_are_dropped_with_a_reason():
    flat = _pair(lag=4, dn_heights=(10,))  # hilir hampir tidak naik
    assert event_lags(flat, "up", "dn", threshold=80)[1]["hilir_tidak_naik"] == 1
    early = _pair(lag=-2)  # puncak hilir lebih dulu: bukan kiriman dari hulu
    assert event_lags(early, "up", "dn", threshold=80)[1]["hilir_lebih_dulu"] == 1
    gap = _pair(lag=4)
    gap.iloc[52, 1] = np.nan
    assert event_lags(gap, "up", "dn", threshold=80)[1]["nan"] == 1
