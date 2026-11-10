import pytest

from settings import ENV_OVERRIDES, load_config


def test_load_config_reads_project_and_tables_for_both_modules():
    for name in ("preprocessing", "prediction"):
        config = load_config(name)
        assert "project" in config
        assert "dataset" in config
        assert "tables" in config


@pytest.fixture
def clean_env(monkeypatch):
    for env_var in ENV_OVERRIDES:
        monkeypatch.delenv(env_var, raising=False)
    return monkeypatch


def test_env_overrides_project_dataset_location(clean_env):
    clean_env.setenv("GCP_PROJECT", "staging-project")
    clean_env.setenv("BQ_DATASET", "staging_ds")
    clean_env.setenv("BQ_LOCATION", "asia-southeast2")
    for name in ("raw_preprocessing", "rainfall", "preprocessing", "prediction"):
        config = load_config(name)
        assert (config["project"], config["dataset"], config["location"]) == (
            "staging-project", "staging_ds", "asia-southeast2")


def test_blank_env_var_keeps_yaml_value(clean_env):
    clean_env.setenv("GCP_PROJECT", "   ")
    assert load_config("prediction")["project"] != ""


def test_prediction_model_settings_cover_both_granularities():
    model = load_config("prediction")["model"]
    for granularity in ("hourly", "daily"):
        assert {"lookback", "horizons", "step"} <= set(model[granularity])
