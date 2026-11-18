"""Import of hourly values into Home Assistant long-term statistics (external statistics).

The energy statistic carries `state` = kWh of the hour and `sum` = running total. Writing an hour
again recomputes the total of every later hour, so a correction never leaves a jump behind.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder import models as recorder_models
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .energy import HourValue

# Home Assistant ≥ 2025.4 replaced `has_mean` by `mean_type`; both are supported here.
_MEAN_TYPE: Any = getattr(recorder_models, "StatisticMeanType", None)


def statistic_id(prm: str, kind: str, production: bool = False) -> str:
    """`enedis_entreprise:<prm>_energy`, `…_power`, with `_production` for injected energy."""
    return f"{DOMAIN}:{prm}_{kind}{'_production' if production else ''}"


def _metadata(ident: str, name: str, unit: str, unit_class: str, has_sum: bool) -> Any:
    meta: dict[str, Any] = {
        "source": DOMAIN,
        "statistic_id": ident,
        "name": name,
        "unit_of_measurement": unit,
        "has_sum": has_sum,
    }
    if _MEAN_TYPE is None:
        meta["has_mean"] = not has_sum
    else:  # pragma: no cover - depends on the installed Home Assistant
        meta["mean_type"] = _MEAN_TYPE.NONE if has_sum else _MEAN_TYPE.ARITHMETIC
        meta["unit_class"] = unit_class
    return meta


def _start(row: Any) -> datetime:
    start = row["start"]
    return start if isinstance(start, datetime) else datetime.fromtimestamp(start, UTC)


async def async_import_hours(
    hass: HomeAssistant, prm: str, production: bool, hours: dict[datetime, HourValue]
) -> None:
    """Write the energy (kWh, with running total) and power (kW) statistics of these hours."""
    if not hours:
        return
    label = "production" if production else "consumption"
    first = min(hours)
    energy_id = statistic_id(prm, "energy", production)
    recorder = get_instance(hass)

    later = (
        await recorder.async_add_executor_job(
            statistics_during_period,
            hass,
            first,
            None,
            {energy_id},
            "hour",
            None,
            {"state", "sum"},
        )  # fmt: skip
    ).get(energy_id, [])
    if later:
        base = (later[0].get("sum") or 0.0) - (later[0].get("state") or 0.0)
    else:
        last = (
            await recorder.async_add_executor_job(
                get_last_statistics, hass, 1, energy_id, True, {"sum"}
            )
        ).get(energy_id, [])
        base = (last[0].get("sum") or 0.0) if last else 0.0

    energy = {_start(row): row.get("state") or 0.0 for row in later}
    energy |= {hour: value.energy_kwh for hour, value in hours.items()}
    rows: list[StatisticData] = []
    total = base
    for hour in sorted(energy):
        total += energy[hour]
        rows.append(StatisticData(start=hour, state=energy[hour], sum=total))
    async_add_external_statistics(
        hass,
        _metadata(energy_id, f"Enedis {prm} {label}", UnitOfEnergy.KILO_WATT_HOUR, "energy", True),
        rows,
    )
    async_add_external_statistics(
        hass,
        _metadata(
            statistic_id(prm, "power", production),
            f"Enedis {prm} {label} power",
            UnitOfPower.KILO_WATT,
            "power",
            False,
        ),
        [
            StatisticData(start=hour, mean=value.mean_kw, min=value.min_kw, max=value.max_kw)
            for hour, value in sorted(hours.items())
        ],
    )
