"""Shared fixtures for the Scenario Quality Checker tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quality_checker.webapp.server import app

EXAMPLES = Path(__file__).resolve().parent.parent / "example_files"


@pytest.fixture
def client():
    """A test client with the application lifespan running."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def example():
    """Return a callable resolving an example scenario by name."""

    def resolve(name):
        path = EXAMPLES / name
        assert path.is_file(), f"missing example file {name}"
        return path

    return resolve


def upload(path, field="scenario"):
    """Build a multipart payload for one example file."""
    return {field: (path.name, path.read_bytes(), "application/xml")}


def created(response):
    """Return the JSON body of a successful check, reporting the error if not."""
    assert response.status_code == 201, f"{response.status_code}: {response.text[:500]}"
    return response.json()
