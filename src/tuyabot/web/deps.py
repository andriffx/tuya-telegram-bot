"""Dependency injection untuk REST API."""

import os

from ..config import DEVICES

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")


def get_device_names() -> set[str]:
    return set(DEVICES.keys())
