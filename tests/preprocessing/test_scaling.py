import pandas as pd
import pytest

from preprocessing.scaling import apply_scalers, fit_scalers, make_bq_frame, to_bq_column


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Bendung Katulampa", "Bendung_Katulampa"),
        ("station-1", "station_1"),
        ("already_ok", "already_ok"),
    ],
)
def test_to_bq_column_sanitizes_invalid_characters(raw, expected):
    assert to_bq_column(raw) == expected


def test_fit_and_apply_scalers_maps_train_range_to_unit_interval():
    df_train = pd.DataFrame({"station_a": [0.0, 50.0, 100.0]})

    scalers = fit_scalers(df_train, ["station_a"])
    scaled = apply_scalers(df_train, scalers, ["station_a"])

    assert scaled["station_a"].min() == pytest.approx(0.0)
    assert scaled["station_a"].max() == pytest.approx(1.0)


def test_apply_scalers_leaves_nan_untouched():
    df_train = pd.DataFrame({"station_a": [0.0, 50.0, 100.0]})
    scalers = fit_scalers(df_train, ["station_a"])

    df_other = pd.DataFrame({"station_a": [25.0, None]})
    scaled = apply_scalers(df_other, scalers, ["station_a"])

    assert scaled["station_a"].isna().sum() == 1
    assert scaled["station_a"].iloc[0] == pytest.approx(0.25)


def test_make_bq_frame_renames_columns_and_tags_split():
    index = pd.date_range("2024-01-01", periods=2, freq="h", name="datetime")
    df = pd.DataFrame({"Bendung Katulampa": [1.0, 2.0]}, index=index)
    column_map = {"Bendung Katulampa": "Bendung_Katulampa"}

    out = make_bq_frame(df, "train", column_map)

    assert list(out.columns) == ["datetime", "Bendung_Katulampa", "split"]
    assert (out["split"] == "train").all()
