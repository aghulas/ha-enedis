"""Sensors: reception status, last measure per meter, and the latest R64 index of each series."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnedisConfigEntry
from .const import DOMAIN
from .coordinator import EnedisCoordinator

# R64 quantities → (label, device class, state class). Units come from the file itself.
QUANTITIES: dict[str, tuple[str, SensorDeviceClass | None, SensorStateClass | None]] = {
    "EA": ("Active energy index", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING),
    "ER": ("Reactive energy index", None, SensorStateClass.TOTAL_INCREASING),
    "ERC": ("Capacitive reactive energy index", None, SensorStateClass.TOTAL_INCREASING),
    "ERI": ("Inductive reactive energy index", None, SensorStateClass.TOTAL_INCREASING),
    "PMA": ("Max power reached", SensorDeviceClass.APPARENT_POWER, SensorStateClass.MEASUREMENT),
    "DD": ("Overrun duration", SensorDeviceClass.DURATION, None),
    "DE": ("Overrun energy", SensorDeviceClass.ENERGY, None),
    "DQ": ("Quadratic overrun", None, None),
    "TF": ("Operating time", SensorDeviceClass.DURATION, None),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: EnedisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [LastFileSensor(coordinator, entry), FilesProcessedSensor(coordinator, entry)]
    )
    known: set[str] = set()

    @callback
    def add_new() -> None:
        """Meters and index series appear as files arrive."""
        entities: list[SensorEntity] = []
        data = coordinator.data
        for prm in set(data.last_point) | set(data.indexes):
            if prm not in known:
                known.add(prm)
                entities.append(LastPointSensor(coordinator, prm))
            for key in data.indexes.get(prm, {}):
                if f"{prm}|{key}" not in known:
                    known.add(f"{prm}|{key}")
                    entities.append(IndexSensor(coordinator, prm, key))
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class _EntrySensor(CoordinatorEntity[EnedisCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EnedisCoordinator, entry: EnedisConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Enedis",
            entry_type=DeviceEntryType.SERVICE,
        )


class LastFileSensor(_EntrySensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: EnedisCoordinator, entry: EnedisConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_file")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.last_file


class FilesProcessedSensor(_EntrySensor):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: EnedisCoordinator, entry: EnedisConfigEntry) -> None:
        super().__init__(coordinator, entry, "files_processed")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.files_processed


class _MeterSensor(CoordinatorEntity[EnedisCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnedisCoordinator, prm: str) -> None:
        super().__init__(coordinator)
        self._prm = prm
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, prm)}, name=f"PRM {prm}", manufacturer="Enedis"
        )


class LastPointSensor(_MeterSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_point"

    def __init__(self, coordinator: EnedisCoordinator, prm: str) -> None:
        super().__init__(coordinator, prm)
        self._attr_unique_id = f"{prm}_last_point"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.last_point.get(self._prm)


class IndexSensor(_MeterSensor):
    """Latest value of one index series (quantity, grid, calendar, time class)."""

    def __init__(self, coordinator: EnedisCoordinator, prm: str, key: str) -> None:
        super().__init__(coordinator, prm)
        self._key = key
        index = self._index
        quantity = index.get("grandeur_physique") or ""
        label, device_class, state_class = QUANTITIES.get(quantity, (quantity, None, None))
        where = index.get("class_label") or index.get("class_id") or index.get("dial")
        production = " (production)" if index.get("grandeur_metier") == "PROD" else ""
        grid = {"D": "distributor", "F": "supplier"}.get(index.get("grid") or "")
        self._attr_name = " – ".join(part for part in (label + production, where, grid) if part)
        self._attr_unique_id = f"{prm}_{key}"
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = index.get("unit")

    @property
    def _index(self) -> dict[str, Any]:
        return self.coordinator.data.indexes.get(self._prm, {}).get(self._key, {})

    @property
    def native_value(self) -> int | None:
        return self._index.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        index = self._index
        return {
            "reading_time": index.get("timestamp"),
            "context": index.get("context"),
            "reading_type": index.get("reading_type"),
        }
