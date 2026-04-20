"""Constants for the LYWSD02 Clock integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "lywsd02_clock"
MANUFACTURER: Final = "Xiaomi"
MODEL: Final = "LYWSD02"

CONF_MAC: Final = "mac"
CONF_NAME: Final = "name"
CONF_FREQUENCY: Final = "frequency"
CONF_TEMP_UNIT: Final = "temp_unit"
CONF_CLOCK_MODE: Final = "clock_mode"
CONF_AUTO_SYNC: Final = "auto_sync"

FREQUENCY_DAILY: Final = "daily"
FREQUENCY_WEEKLY: Final = "weekly"
FREQUENCY_MONTHLY: Final = "monthly"
FREQUENCIES: Final = [FREQUENCY_DAILY, FREQUENCY_WEEKLY, FREQUENCY_MONTHLY]

TEMP_UNIT_C: Final = "C"
TEMP_UNIT_F: Final = "F"
TEMP_UNITS: Final = [TEMP_UNIT_C, TEMP_UNIT_F]

CLOCK_MODE_12: Final = 12
CLOCK_MODE_24: Final = 24
CLOCK_MODES: Final = [CLOCK_MODE_12, CLOCK_MODE_24]

DEFAULT_FREQUENCY: Final = FREQUENCY_DAILY
DEFAULT_TEMP_UNIT: Final = TEMP_UNIT_C
DEFAULT_CLOCK_MODE: Final = CLOCK_MODE_24
DEFAULT_AUTO_SYNC: Final = True
DEFAULT_TIMEOUT: Final = 60.0

SYNC_HOUR: Final = 3
SYNC_MINUTE: Final = 30
DST_CHECK_MINUTE: Final = 35

UUID_TIME: Final = "EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6"
UUID_UNIT: Final = "EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6"

STATUS_SUCCESS: Final = "success"
STATUS_FAILED: Final = "failed"
STATUS_NEVER: Final = "never"

SERVICE_SET_TIME: Final = "set_time"
