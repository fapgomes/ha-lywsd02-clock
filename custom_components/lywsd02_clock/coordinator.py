"""Scheduler + sync coordinator for an LYWSD02 clock entry."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_SYNC,
    CONF_CLOCK_MODE,
    CONF_FREQUENCY,
    CONF_TEMP_UNIT,
    DEFAULT_AUTO_SYNC,
    DEFAULT_CLOCK_MODE,
    DEFAULT_FREQUENCY,
    DEFAULT_TEMP_UNIT,
    DOMAIN,
    DST_CHECK_MINUTE,
    FREQUENCY_DAILY,
    FREQUENCY_DST_ONLY,
    FREQUENCY_MONTHLY,
    FREQUENCY_WEEKLY,
    STATUS_FAILED,
    STATUS_NEVER,
    STATUS_SUCCESS,
    SYNC_HOUR,
    SYNC_MINUTE,
)
from .device import DeviceCommunicationError, DeviceNotFoundError, set_time

_LOGGER = logging.getLogger(__name__)


def is_sync_day(now: datetime, frequency: str) -> bool:
    if frequency == FREQUENCY_DAILY:
        return True
    if frequency == FREQUENCY_WEEKLY:
        return now.weekday() == 6
    if frequency == FREQUENCY_MONTHLY:
        return now.day == 1
    # FREQUENCY_DST_ONLY: never on the scheduled tick; DST check handles it.
    return False


def compute_next_sync(now: datetime, frequency: str) -> datetime | None:
    if frequency == FREQUENCY_DST_ONLY:
        return None
    candidate = now.replace(hour=SYNC_HOUR, minute=SYNC_MINUTE, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while not is_sync_day(candidate, frequency):
        candidate += timedelta(days=1)
    return candidate


class LYWSD02Coordinator(DataUpdateCoordinator[None]):
    """Owns the schedule, runtime state, and the shared async_sync path."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{mac}")
        self.entry = entry
        self.mac = mac
        self.last_sync: datetime | None = None
        self.last_attempt: datetime | None = None
        self.last_status: str = STATUS_NEVER
        self.last_error: str | None = None
        self.last_utcoffset: Any = None
        self._unsub: list[CALLBACK_TYPE] = []

    @property
    def frequency(self) -> str:
        return self.entry.options.get(
            CONF_FREQUENCY, self.entry.data.get(CONF_FREQUENCY, DEFAULT_FREQUENCY)
        )

    @property
    def temp_unit(self) -> str:
        return self.entry.options.get(
            CONF_TEMP_UNIT, self.entry.data.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT)
        )

    @property
    def clock_mode(self) -> int:
        raw = self.entry.options.get(
            CONF_CLOCK_MODE, self.entry.data.get(CONF_CLOCK_MODE, DEFAULT_CLOCK_MODE)
        )
        return int(raw)

    @property
    def auto_sync_enabled(self) -> bool:
        return bool(
            self.entry.options.get(
                CONF_AUTO_SYNC, self.entry.data.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC)
            )
        )

    @callback
    def start_schedule(self) -> None:
        """Register the daily tick and DST-check callbacks."""
        self._unsub.append(
            async_track_time_change(
                self.hass,
                self._on_schedule_tick,
                hour=SYNC_HOUR,
                minute=SYNC_MINUTE,
                second=0,
            )
        )
        self._unsub.append(
            async_track_time_change(
                self.hass,
                self._on_dst_check,
                hour=SYNC_HOUR,
                minute=DST_CHECK_MINUTE,
                second=0,
            )
        )
        self.last_utcoffset = dt_util.now().utcoffset()

    @callback
    def shutdown(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    async def _on_schedule_tick(self, now: datetime) -> None:
        if not self.auto_sync_enabled:
            return
        if not is_sync_day(dt_util.as_local(now), self.frequency):
            return
        await self.async_sync()

    async def _on_dst_check(self, now: datetime) -> None:
        current_offset = dt_util.now().utcoffset()
        if (
            self.auto_sync_enabled
            and self.last_utcoffset is not None
            and current_offset != self.last_utcoffset
        ):
            _LOGGER.info(
                "DST transition detected for %s (%s -> %s); forcing sync",
                self.mac,
                self.last_utcoffset,
                current_offset,
            )
            await self.async_sync()
        self.last_utcoffset = current_offset

    async def async_sync(self) -> bool:
        """Run a single sync through the shared code path. Returns True on success."""
        self.last_attempt = dt_util.utcnow()
        try:
            await set_time(
                self.hass,
                self.mac,
                temp_unit=self.temp_unit,
                clock_mode=self.clock_mode,
            )
        except (DeviceNotFoundError, DeviceCommunicationError) as exc:
            self.last_status = STATUS_FAILED
            self.last_error = str(exc)
            _LOGGER.warning("Sync failed for %s: %s", self.mac, exc)
            self.async_update_listeners()
            return False
        except Exception as exc:  # noqa: BLE001 — defensive catch for the coordinator
            self.last_status = STATUS_FAILED
            self.last_error = f"Unexpected error: {exc}"
            _LOGGER.exception("Unexpected error syncing %s", self.mac)
            self.async_update_listeners()
            return False

        self.last_sync = dt_util.utcnow()
        self.last_status = STATUS_SUCCESS
        self.last_error = None
        self.last_utcoffset = dt_util.now().utcoffset()
        self.async_update_listeners()
        return True

    def compute_next_sync(self) -> datetime | None:
        if not self.auto_sync_enabled:
            return None
        return compute_next_sync(dt_util.now(), self.frequency)

    async def async_initial_sync_if_needed(self) -> None:
        """Trigger a one-shot sync if this coordinator has never synced yet."""
        if self.last_sync is None and self.auto_sync_enabled:
            await self.async_sync()
