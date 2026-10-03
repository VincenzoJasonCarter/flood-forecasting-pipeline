import pytest

from raw_preprocessing.pipeline import run


def test_run_rejects_unknown_granularity_before_crawling():
    # Raises before get_token/crawl_range, so no token or network is needed.
    with pytest.raises(ValueError, match="granularity"):
        run(granularity="weekly")
