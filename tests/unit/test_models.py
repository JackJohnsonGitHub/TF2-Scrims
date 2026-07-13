"""Unit tests for the Server view model and settings validation."""
from app.models import Server, validate_server_settings


def _server(**kw):
    base = dict(id="s", name="S", map="cp_x", status="online",
               players=3, max_slots=24, address="1.2.3.4:27015")
    base.update(kw)
    return Server(**base)


def test_slots_display():
    assert _server(players=12, max_slots=24).slots_display == "12/24"


def test_status_helpers():
    assert _server(status="online").is_online is True
    assert _server(status="offline").status_label == "Offline"


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
