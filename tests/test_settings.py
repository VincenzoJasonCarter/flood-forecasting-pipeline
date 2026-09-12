from settings import load_config


def test_load_config_reads_project_and_tables_for_both_modules():
    for name in ("preprocessing", "prediction"):
        config = load_config(name)
        assert "project" in config
        assert "dataset" in config
        assert "tables" in config
