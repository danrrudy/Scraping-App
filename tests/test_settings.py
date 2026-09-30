import copy
import json

from app_settings import (
    VERSION_KEY,
    default_settings,
    load_settings,
    save_settings,
    settings_version_mismatch,
    stamp_settings_version,
)
from version import __version__


def test_missing_settings_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "user_settings.json"

    loaded = load_settings(path)

    assert loaded == default_settings
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == default_settings


def test_user_settings_merge_with_defaults_and_ignore_unknown_keys(tmp_path):
    path = tmp_path / "user_settings.json"
    log_directory = tmp_path / "custom-logs"
    path.write_text(
        json.dumps(
            {
                "fontSize": "16",
                "logFileDirectory": str(log_directory),
                "unknownSetting": "ignored",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_settings(path)

    assert loaded["fontSize"] == "16"
    assert loaded["MIDLocation"] == default_settings["MIDLocation"]
    assert "unknownSetting" not in loaded
    assert log_directory.is_dir()


def test_invalid_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "user_settings.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert load_settings(path) == default_settings


def test_settings_round_trip_preserves_serializable_values(tmp_path):
    path = tmp_path / "user_settings.json"
    expected = copy.deepcopy(default_settings)
    expected.update(
        {
            "userMode": "Reviewer",
            "UIScale": "0.9",
            "fieldButtons": [
                {"label": "10%", "target": "Match", "expression": "LMIG_Exp * 0.1"}
            ],
        }
    )

    save_settings(expected, path)

    assert load_settings(path) == expected


def test_settings_saved_with_a_byte_order_mark_still_load(tmp_path):
    """Several Windows editors write a BOM; it must not reset the settings."""
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps({"fontSize": "18"}), encoding="utf-8-sig")

    loaded = load_settings(path)

    assert loaded["fontSize"] == "18"


# ----------------------------------------------------------------------
# Version stamping
# ----------------------------------------------------------------------
def test_a_fresh_settings_file_is_stamped_with_this_version(tmp_path):
    path = tmp_path / "user_settings.json"

    loaded = load_settings(path)

    assert loaded[VERSION_KEY] == __version__
    assert settings_version_mismatch(loaded) is None


def test_saving_stamps_the_file_with_the_version_writing_it(tmp_path):
    path = tmp_path / "user_settings.json"
    settings = copy.deepcopy(default_settings)
    settings[VERSION_KEY] = "0.0.1"

    save_settings(settings, path)

    assert json.loads(path.read_text(encoding="utf-8"))[VERSION_KEY] == __version__


def test_a_file_from_another_version_is_reported_as_such(tmp_path):
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps({VERSION_KEY: "0.9.0"}), encoding="utf-8")

    loaded = load_settings(path)

    assert settings_version_mismatch(loaded) == ("0.9.0", __version__)


def test_a_file_from_before_stamping_reads_as_an_earlier_version(tmp_path):
    """Merging defaults must not make an old file look like this version."""
    path = tmp_path / "user_settings.json"
    path.write_text(json.dumps({"fontSize": "16"}), encoding="utf-8")

    loaded = load_settings(path)

    assert settings_version_mismatch(loaded) == ("an earlier version", __version__)


def test_stamping_reports_whether_anything_changed():
    settings = {VERSION_KEY: "0.9.0"}

    assert stamp_settings_version(settings) is True
    assert settings[VERSION_KEY] == __version__
    assert stamp_settings_version(settings) is False


# ----------------------------------------------------------------------
# The start-up check
# ----------------------------------------------------------------------
def test_matching_versions_ask_nothing(silent_logger, monkeypatch):
    import main

    asked = []
    settings = copy.deepcopy(default_settings)

    assert main.confirm_settings_version(
        settings, silent_logger, ask=lambda *args: asked.append(args)
    )
    assert asked == []


def test_declining_the_mismatch_stops_the_program(silent_logger, monkeypatch):
    import main
    from PyQt5.QtWidgets import QMessageBox

    saved = []
    monkeypatch.setattr(main, "save_settings", lambda settings: saved.append(settings))
    settings = dict(default_settings, **{VERSION_KEY: "0.9.0"})

    proceed = main.confirm_settings_version(
        settings, silent_logger, ask=lambda *args: QMessageBox.No
    )

    assert proceed is False
    assert saved == []
    assert settings[VERSION_KEY] == "0.9.0"


def test_accepting_the_mismatch_restamps_so_it_is_asked_once(
    silent_logger, monkeypatch
):
    import main
    from PyQt5.QtWidgets import QMessageBox

    saved = []
    monkeypatch.setattr(main, "save_settings", lambda settings: saved.append(settings))
    settings = dict(default_settings, **{VERSION_KEY: "0.9.0"})
    questions = []

    def ask(parent, title, text, *rest):
        questions.append(text)
        return QMessageBox.Yes

    assert main.confirm_settings_version(settings, silent_logger, ask=ask) is True
    assert "0.9.0" in questions[0] and __version__ in questions[0]
    assert saved == [settings]
    assert settings[VERSION_KEY] == __version__
    assert settings_version_mismatch(settings) is None
