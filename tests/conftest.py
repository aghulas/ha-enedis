from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load `custom_components/` — only for tests that use `hass`."""
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_mock")  # must exist before `hass`
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
