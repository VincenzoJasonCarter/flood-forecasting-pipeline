"""BigQuery client for the prediction package (project/location from config/prediction.yaml)."""

from bq import authenticate, make_client

from .config import LOCATION, PROJECT_ID


def get_client():
    return make_client(PROJECT_ID, LOCATION)


__all__ = ["authenticate", "get_client"]
