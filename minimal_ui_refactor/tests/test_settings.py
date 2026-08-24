import copy
import json

from app_settings import default_settings, load_settings, save_settings


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
    expected = default_settings.copy()
    expected.update(
        {
            "userMode": "Reviewer",
            "UIScale": "0.9",
            "evaluationClasses": {
                "Performance": {"option_types": ["Met", "Not Met"]}
            },
        }
    )

    save_settings(expected, path)

    assert load_settings(path) == expected



def test_settings_saved_with_a_byte_order_mark_still_load(tmp_path):
    """Several Windows editors add a BOM. Losing the file to it is not an option.

    Reading such a file as plain utf-8 raises, which the loader answers with
    defaults — and the next save would then write those defaults over the
    user's real configuration.
    """
    path = tmp_path / "user_settings.json"
    expected = copy.deepcopy(default_settings)
    expected["MIDSheetName"] = "Sheet configured by hand"
    path.write_text(json.dumps(expected), encoding="utf-8-sig")

    assert load_settings(path)["MIDSheetName"] == "Sheet configured by hand"
