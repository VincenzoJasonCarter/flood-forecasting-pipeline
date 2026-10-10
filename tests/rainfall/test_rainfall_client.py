import pytest

from rainfall.client import Throttle, request_weight, total_weight


def test_request_weight_counts_locations_and_two_week_blocks():
    assert request_weight(1, 1) == 1
    assert request_weight(50, 1) == 50
    assert request_weight(10, 28) == 20
    assert request_weight(10, 366) == pytest.approx(261.4, abs=0.1)


def test_total_weight_sums_all_chunks():
    # 25 sel -> batch 10, 10, 5; 2024 = 366 hari = 1 potongan waktu
    assert total_weight(25, "2024-01-01", "2024-12-31") == pytest.approx(25 * 366 / 14)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_throttle_passes_through_under_budget():
    clock = FakeClock()
    t = Throttle(limits=((60, 100),), clock=clock, sleep=clock.sleep)
    for _ in range(4):
        t.wait(25)
    assert clock.sleeps == []


def test_throttle_waits_until_oldest_requests_expire():
    clock = FakeClock()
    t = Throttle(limits=((60, 100),), clock=clock, sleep=clock.sleep)
    t.wait(60)           # t=0
    clock.now = 10
    t.wait(30)           # t=10, total 90
    clock.now = 20
    t.wait(30)           # butuh entri t=0 (60) kedaluwarsa -> tunggu s/d t=60
    assert clock.now >= 60
    assert len(clock.sleeps) == 1


def test_throttle_respects_every_window():
    clock = FakeClock()
    t = Throttle(limits=((60, 100), (3600, 150)), clock=clock, sleep=clock.sleep)
    t.wait(100)          # t=0
    clock.now = 61
    t.wait(50)           # menit sudah lewat, jam: 150 pas
    t.wait(10)           # jam penuh -> tunggu s/d entri t=0 lewat 3600 detik
    assert clock.now >= 3600


def test_throttle_rejects_request_heavier_than_budget():
    clock = FakeClock()
    t = Throttle(limits=((60, 100),), clock=clock, sleep=clock.sleep)
    with pytest.raises(ValueError):
        t.wait(101)
