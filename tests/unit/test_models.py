"""Unit tests for server settings validation.

The `Server` view model that used to live here went away with feature 005: servers are
persisted rows now, and their display formatting lives in `app/servers_store.py` — in
one place, so there is no second formatting path to keep in step. See
tests/unit/test_servers_store.py for those.
"""
from app.models import validate_server_settings


def test_valid_settings_pass():
    assert validate_server_settings("Friday PUG", "cp_process_final", "24", "") == {}


def test_missing_name_fails():
    errors = validate_server_settings("   ", "cp_x", "24", "")
    assert "name" in errors


def test_missing_map_fails():
    errors = validate_server_settings("Name", "", "24", "")
    assert "map" in errors


def test_slots_out_of_range_fails():
    assert "max_slots" in validate_server_settings("Name", "cp_x", "0", "")
    assert "max_slots" in validate_server_settings("Name", "cp_x", "33", "")


def test_slots_non_integer_fails():
    assert "max_slots" in validate_server_settings("Name", "cp_x", "twenty", "")


def test_whitespace_only_password_fails():
    assert "join_password" in validate_server_settings("Name", "cp_x", "24", "   ")


def test_name_too_long_fails():
    assert "name" in validate_server_settings("x" * 65, "cp_x", "24", "")
