import json
import logging

import logging_setup


def _emit(capsys, monkeypatch, **env):
    for key in ("LOG_FORMAT", "LOG_LEVEL", "CLOUD_RUN_JOB", "K_SERVICE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    logging_setup.configure_logging()
    logging.getLogger("demo").warning("halo %s", "dunia")
    return capsys.readouterr().out.strip()


def test_text_format_by_default(capsys, monkeypatch):
    line = _emit(capsys, monkeypatch)
    assert line.endswith("WARNING demo: halo dunia")


def test_json_with_severity_on_cloud_run(capsys, monkeypatch):
    entry = json.loads(_emit(capsys, monkeypatch, CLOUD_RUN_JOB="flood-hourly"))
    assert entry == {"severity": "WARNING", "logger": "demo", "message": "halo dunia"}


def test_log_format_overrides_environment_detection(capsys, monkeypatch):
    line = _emit(capsys, monkeypatch, CLOUD_RUN_JOB="flood-hourly", LOG_FORMAT="text")
    assert not line.startswith("{")


def test_log_level_env(capsys, monkeypatch):
    out = _emit(capsys, monkeypatch, LOG_LEVEL="ERROR")
    assert out == ""
