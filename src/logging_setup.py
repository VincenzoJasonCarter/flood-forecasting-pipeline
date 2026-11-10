"""Logging setup for the CLI entrypoints.

Di Cloud Run (env CLOUD_RUN_JOB / K_SERVICE ada) log ditulis sebagai JSON satu
baris dengan field `severity`, supaya Cloud Logging mengenali levelnya; di
tempat lain berupa teks biasa. Override dengan LOG_FORMAT=json|text, dan level
dengan LOG_LEVEL (default INFO).
"""

import json
import logging
import os
import sys


class _CloudLoggingFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "severity": record.levelname,
            "logger": record.name,
            "message": super().format(record),  # termasuk traceback kalau ada
        }, ensure_ascii=False)


def _use_json():
    explicit = os.environ.get("LOG_FORMAT", "").lower()
    if explicit:
        return explicit == "json"
    return bool(os.environ.get("CLOUD_RUN_JOB") or os.environ.get("K_SERVICE"))


def configure_logging(level=None):
    handler = logging.StreamHandler(sys.stdout)
    if _use_json():
        handler.setFormatter(_CloudLoggingFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel((level or os.environ.get("LOG_LEVEL", "INFO")).upper())
