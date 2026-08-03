"""MAC address helpers shared by the config flow, setup and service schema."""
from __future__ import annotations

import re

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase colon-separated form."""
    return mac.strip().lower()


def is_valid_mac(mac: str) -> bool:
    """Return True if mac is a colon-separated MAC address (any case)."""
    return bool(MAC_RE.match(normalize_mac(mac)))
