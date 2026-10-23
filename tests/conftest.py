"""Keep the entire test suite offline, including the pipeline smoke test."""

import pytest
import requests


@pytest.fixture(autouse=True)
def forbid_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live HTTP is forbidden in tests; inject a mocked client")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
