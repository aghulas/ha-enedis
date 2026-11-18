from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.enedis_entreprise.energy import Buffer, hour_values, merge, newest, prune

T0 = datetime(2026, 3, 1, 8, tzinfo=UTC)
H0 = int(T0.timestamp())


def points(start: datetime, values: list[int]) -> list[tuple[datetime, int, int]]:
    return [(start + timedelta(minutes=5 * i), value, 300) for i, value in enumerate(values)]


def test_hour_from_two_halves_and_idempotence() -> None:
    buffer: Buffer = {}
    assert merge(buffer, points(T0, [12000] * 6)) == {H0}
    half = hour_values(buffer, {H0})[T0]
    assert (half.energy_kwh, half.covered_seconds) == (pytest.approx(6.0), 1800)

    assert merge(buffer, points(T0 + timedelta(minutes=30), [36000] * 6)) == {H0}
    full = hour_values(buffer, {H0})[T0]
    assert full.energy_kwh == pytest.approx(24.0)
    assert (full.mean_kw, full.min_kw, full.max_kw) == (pytest.approx(24.0), 12.0, 36.0)
    assert full.covered_seconds == 3600

    # Same points again: nothing changed, nothing to import.
    assert merge(buffer, points(T0, [12000] * 6)) == set()


def test_correction_replaces_and_other_hours_are_left_alone() -> None:
    buffer: Buffer = {}
    merge(buffer, points(T0, [10000] * 24))
    assert merge(buffer, points(T0 + timedelta(minutes=5), [22000])) == {H0}
    values = hour_values(buffer, {H0})
    assert list(values) == [T0]
    assert values[T0].energy_kwh == pytest.approx(11.0)
    assert hour_values(buffer, {H0 - 3600}) == {}


def test_prune() -> None:
    buffer: Buffer = {}
    assert newest(buffer) == datetime.fromtimestamp(0, UTC)
    merge(buffer, points(T0, [1] * 24))
    assert newest(buffer) == T0 + timedelta(minutes=115)
    prune(buffer, T0 + timedelta(hours=1))
    assert len(buffer) == 12 and min(map(int, buffer)) == H0 + 3600
