from prediction.features import feature_cols_for, required_history, split_model_name

META = {
    "feature_cols": ["A", "B", "cal"],
    "base_feature_cols": ["A", "B", "cal"],
    "feature_cols_by_station": {"A": ["A", "B", "cal", "rain_A_1h"], "B": ["A", "B", "cal"]},
    "rain_accum_hours": [1, 3, 24],
}


def test_split_model_name():
    assert split_model_name("lstm") == ("lstm", True)
    assert split_model_name("tft_norain") == ("tft", False)
    assert split_model_name("prophet_norain") == ("prophet", False)


def test_feature_cols_for_station_with_and_without_rain():
    assert feature_cols_for(META, "A") == ["A", "B", "cal", "rain_A_1h"]
    assert feature_cols_for(META, "A", use_rain=False) == ["A", "B", "cal"]
    assert feature_cols_for(META, "B") == ["A", "B", "cal"]


def test_feature_cols_for_old_metadata_uses_shared_feature_cols():
    old = {"feature_cols": ["A", "B", "hour"]}
    assert feature_cols_for(old, "A") == ["A", "B", "hour"]


def test_required_history_covers_longest_rain_window():
    assert required_history(META, 72) == 72 + 24 - 1
    assert required_history({"feature_cols": []}, 72) == 72
