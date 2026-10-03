from raw_preprocessing.parsing import flatten_records


def _row(station_id, name, tanggal, jam, ketinggian):
    return {
        "pos_pengamatan": {"id": station_id, "name": name, "aliran": "Aliran Tengah"},
        "tanggal": tanggal,
        "jam": jam,
        "ketinggian": ketinggian,
        "status_siaga": "4",
        "cuaca": {"nama": "Terang"},
    }


def test_flatten_records_types_dedups_and_sorts():
    raw = [
        _row(2, "Pos B", "2024-01-01", "01:00", "30"),
        _row(1, "Pos A", "2024-01-01", "01:00", "-"),  # non-numeric -> NaN
        _row(1, "Pos A", "2024-01-01", "00:00", "10"),
        _row(1, "Pos A", "2024-01-01", "00:00", "99"),  # duplicate -> first kept
    ]

    df = flatten_records(raw)

    assert df["station_name"].tolist() == ["Pos A", "Pos A", "Pos B"]
    assert df["datetime"].dt.hour.tolist() == [0, 1, 1]
    assert df["water_level"].iloc[0] == 10
    assert df["water_level"].isna().iloc[1]
    assert str(df["alert_level"].dtype) == "Int64"
