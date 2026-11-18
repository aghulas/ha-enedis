"""Pure aggregation of curve points into hourly values. No Home Assistant import here.

Points are kept in a buffer keyed by their UTC start (epoch seconds, as text because the buffer
is stored as JSON): the same instant received again replaces the previous value, which is what
makes a file processed twice a no-op and lets late corrections win.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

Buffer = dict[str, list[int]]  # epoch seconds → [value in W, step in seconds]
HOUR = 3600


@dataclass(frozen=True, slots=True)
class HourValue:
    energy_kwh: float
    mean_kw: float
    min_kw: float
    max_kw: float
    covered_seconds: int


def merge(buffer: Buffer, points: Iterable[tuple[datetime, int, int]]) -> set[int]:
    """Add (UTC start, W, step seconds) points; returns the hours (epoch) whose content changed."""
    touched: set[int] = set()
    for start, value, step in points:
        epoch = int(start.timestamp())
        entry = [value, step]
        if buffer.get(str(epoch)) != entry:
            buffer[str(epoch)] = entry
            touched.add(epoch - epoch % HOUR)
    return touched


def hour_values(buffer: Buffer, hours: Iterable[int]) -> dict[datetime, HourValue]:
    """Values of the given hours (epoch), from every point of the buffer that starts in them."""
    wanted = set(hours)
    groups: dict[int, list[list[int]]] = {}
    for key, entry in buffer.items():
        hour = int(key) - int(key) % HOUR
        if hour in wanted:
            groups.setdefault(hour, []).append(entry)
    out: dict[datetime, HourValue] = {}
    for hour, entries in sorted(groups.items()):
        seconds = sum(step for _, step in entries)
        watt_seconds = sum(value * step for value, step in entries)
        values = [value for value, _ in entries]
        out[datetime.fromtimestamp(hour, UTC)] = HourValue(
            energy_kwh=watt_seconds / 3_600_000,
            mean_kw=watt_seconds / seconds / 1000,
            min_kw=min(values) / 1000,
            max_kw=max(values) / 1000,
            covered_seconds=seconds,
        )
    return out


def newest(buffer: Buffer) -> datetime:
    """Start of the most recent point (the epoch itself for an empty buffer)."""
    return datetime.fromtimestamp(max(map(int, buffer), default=0), UTC)


def prune(buffer: Buffer, before: datetime) -> None:
    limit = int(before.timestamp())
    for key in [key for key in buffer if int(key) < limit]:
        del buffer[key]
