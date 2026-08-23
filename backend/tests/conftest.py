"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """A TestClient against a freshly built app, so settings overrides don't leak."""
    return TestClient(create_app())
