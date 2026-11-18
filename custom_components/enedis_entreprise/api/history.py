"""One-off history: the CSV exported from the Enedis portal by the `enedis-mcp` connector.

Format: `debut;kw_moyen`, one row per step — start as ISO 8601 with its UTC offset, mean power in
kW with a decimal comma, empty when the point is missing. R6X publications only start at the
subscription date; this fills what came before.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

DEFAULT_STEP = 300


class HistoryError(Exception):
    """The file is not a history export."""


def parse_history_csv(text: str) -> list[tuple[datetime, int, int]]:
    """→ (UTC start, mean power in W, step in seconds), in file order; missing points skipped."""
    rows = csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";")
    header = [cell.strip().lower() for cell in next(rows, [])]
    if header[:2] != ["debut", "kw_moyen"]:
        raise HistoryError("not a history export: the first line must be 'debut;kw_moyen'")
    starts: list[datetime] = []
    values: list[float | None] = []
    for number, row in enumerate(rows, start=2):
        if not any(row):
            continue
        try:
            start = datetime.fromisoformat(row[0].strip())
            cell = row[1].strip() if len(row) > 1 else ""
            value = float(cell.replace(",", ".")) if cell else None
        except ValueError:
            raise HistoryError(f"unreadable row {number}") from None
        if start.tzinfo is None:
            raise HistoryError(f"row {number}: the timestamp has no UTC offset")
        starts.append(start.astimezone(UTC))
        values.append(value)
    step = DEFAULT_STEP
    if len(starts) > 1:
        gaps = sorted(
            int((b - a).total_seconds()) for a, b in zip(starts, starts[1:], strict=False)
        )
        step = gaps[len(gaps) // 2]  # median: holes and clock changes do not disturb it
        if step <= 0 or step > 3600 or 3600 % step:
            raise HistoryError("the step of the file is not a divisor of one hour")
    return [
        (start, round(value * 1000), step)
        for start, value in zip(starts, values, strict=True)
        if value is not None
    ]
