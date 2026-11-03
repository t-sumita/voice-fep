"""Shared pytest fixtures for voice-fep tests."""
import pytest
import main


@pytest.fixture(autouse=True)
def reset_time_guards():
    """Reset time-based gate variables before each test to prevent cross-test contamination."""
    main._last_press_time = 0.0
    main._last_paste_time = 0.0
    main._has_pasted = False
    yield
    main._last_press_time = 0.0
    main._last_paste_time = 0.0
    main._has_pasted = False
