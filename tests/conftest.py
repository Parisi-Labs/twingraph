"""Pytest fixtures for the twingraph suite."""

from __future__ import annotations

import pytest
from helpers import StubModelRegistry, load_demo_doc


@pytest.fixture
def demo_doc() -> dict:
    return load_demo_doc()


@pytest.fixture
def model_registry() -> StubModelRegistry:
    return StubModelRegistry()
