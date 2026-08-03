"""Shared fixtures for the lywsd02_clock test suite."""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the custom integration in every test."""
    yield
