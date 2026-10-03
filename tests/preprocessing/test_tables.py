from preprocessing.config import GRANULARITIES, table_id


def test_every_granularity_has_its_own_table_set():
    for name in ("station_features", "preprocessed_data", "metadata", "scalers"):
        ids = {table_id(name, g) for g in GRANULARITIES}
        assert len(ids) == len(GRANULARITIES), name


def test_input_matches_raw_preprocessing_output():
    from raw_preprocessing.config import station_features_table

    for g in GRANULARITIES:
        assert table_id("station_features", g) == station_features_table(g)
