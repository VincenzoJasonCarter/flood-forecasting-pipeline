"""Load a module's YAML config from the repo-level config/ directory."""

import os
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Env var -> kunci YAML level atas. Memungkinkan mengarahkan semua modul ke
# project/dataset lain (mis. staging) tanpa mengubah file config.
ENV_OVERRIDES = {
    "GCP_PROJECT": "project",
    "BQ_DATASET": "dataset",
    "BQ_LOCATION": "location",
}


def load_config(name):
    path = CONFIG_DIR / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for env_var, key in ENV_OVERRIDES.items():
        value = os.environ.get(env_var, "").strip()
        if value:
            config[key] = value
    return config
