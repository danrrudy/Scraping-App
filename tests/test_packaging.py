"""What has to hold for a packaged build to work.

None of this is observable when running from source, where every location the
application wants happens to be the directory the code is in. Frozen, they come
apart: the code lives somewhere read-only and the files live beside the
program. These tests pin down that separation.
"""

import sys
from pathlib import Path

import pytest

import paths
import starter_plugins


@pytest.fixture(autouse=True)
def forget_resolved_location():
    """The resolved app directory is cached; each test resolves it afresh."""
    paths.reset_cache()
    yield
    paths.reset_cache()


# ----------------------------------------------------------------------
# Where files go
# ----------------------------------------------------------------------
def test_source_checkout_keeps_files_beside_the_code(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.portable_dir() == Path(paths.__file__).resolve().parent


def test_frozen_build_keeps_files_beside_the_executable(monkeypatch, tmp_path):
    installation = tmp_path / "DocumentReviewTool"
    installation.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(installation / "DocumentReviewTool.exe"))
    monkeypatch.setattr(sys, "platform", "win32")

    assert paths.portable_dir() == installation


def test_macos_bundle_keeps_files_beside_the_bundle_not_inside_it(
    monkeypatch, tmp_path
):
    """The one case where "beside the executable" is the wrong answer.

    A signed ``.app`` is read-only inside, so the files belong next to the
    bundle where the user can see them.
    """
    binary = tmp_path / "DocumentReviewTool.app" / "Contents" / "MacOS"
    binary.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary / "DocumentReviewTool"))
    monkeypatch.setattr(sys, "platform", "darwin")

    assert paths.macos_bundle() == tmp_path / "DocumentReviewTool.app"
    assert paths.portable_dir() == tmp_path


def test_macos_bundle_is_none_when_not_a_frozen_mac_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.macos_bundle() is None


def test_unwritable_location_falls_back_instead_of_failing(monkeypatch, tmp_path):
    """Dropped in Program Files, the application still has to start."""
    fallback = tmp_path / "per-user"
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path / "read-only")
    monkeypatch.setattr(paths, "is_writable", lambda directory: False)
    monkeypatch.setattr(paths, "user_data_dir", lambda: fallback)

    assert paths.app_dir() == fallback
    assert "not writable" in paths.location_note()


def test_portable_location_is_reported_as_such(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    assert paths.app_dir() == tmp_path
    assert "portable" in paths.location_note()


def test_location_is_resolved_once(monkeypatch, tmp_path):
    """Files must not end up split across two directories mid-session."""
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path / "first")
    first = paths.app_dir()

    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path / "second")
    assert paths.app_dir() == first


def test_is_writable_answers_by_writing(tmp_path):
    assert paths.is_writable(tmp_path) is True
    assert paths.is_writable(tmp_path / "nested" / "deeper") is True


def test_is_writable_leaves_no_probe_behind(tmp_path):
    paths.is_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_in_app_dir_builds_paths_under_the_app_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    assert paths.in_app_dir("logs") == str(tmp_path / "logs")


# ----------------------------------------------------------------------
# Settings follow the app directory
# ----------------------------------------------------------------------
def test_default_directories_all_sit_under_the_app_directory():
    """A packaged build must not default to writing inside itself."""
    import app_settings

    app_root = str(paths.app_dir())
    for setting in (
        "logFileDirectory",
        "scrapingToolDirectory",
        "dataDirectory",
        "extractionToolDirectory",
    ):
        assert app_settings.default_settings[setting].startswith(app_root)
    assert app_settings.SETTINGS_PATH.startswith(app_root)


# ----------------------------------------------------------------------
# Starter plugins
# ----------------------------------------------------------------------
def test_seeding_installs_the_bundled_plugins(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)

    written = starter_plugins.seed({})

    assert (tmp_path / "scrapers" / "text_scraper.py").is_file()
    assert (tmp_path / "extractors" / "sbstable.py").is_file()
    assert set(written) == {"scrapers", "extractors"}


def test_seeding_honours_configured_plugin_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    elsewhere = tmp_path / "my-scrapers"

    starter_plugins.seed({"scrapingToolDirectory": str(elsewhere)})

    assert (elsewhere / "text_scraper.py").is_file()


def test_seeding_leaves_an_edited_plugin_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    starter_plugins.seed({})

    edited = tmp_path / "scrapers" / "text_scraper.py"
    edited.write_text("# mine now", encoding="utf-8")
    starter_plugins.seed({})

    assert edited.read_text(encoding="utf-8") == "# mine now"


def test_seeding_does_not_restore_a_deleted_plugin(monkeypatch, tmp_path):
    """A folder the user has curated is theirs; we do not put files back."""
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    starter_plugins.seed({})

    scrapers = tmp_path / "scrapers"
    (scrapers / "text_scraper.py").unlink()
    (scrapers / "mine.py").write_text("# a scraper of my own", encoding="utf-8")
    starter_plugins.seed({})

    assert not (scrapers / "text_scraper.py").exists()


def test_bundled_plugins_avoid_the_unpackaged_dependencies():
    """The starter plugins have to run against what the build actually holds.

    PyTorch, Transformers and Tesseract are excluded from the build; a starter
    plugin importing one of them would fail on first use.
    """
    excluded = ("torch", "transformers", "pytesseract")
    bundled = Path(paths.resource_dir()) / "bundled"

    for plugin in bundled.rglob("*.py"):
        source = plugin.read_text(encoding="utf-8")
        for module in excluded:
            assert f"import {module}" not in source, f"{plugin.name} imports {module}"


# ----------------------------------------------------------------------
# Restarting
# ----------------------------------------------------------------------
def _relaunch_command(resume_index):
    from scraping_helper import TextScrapingReviewApp

    return TextScrapingReviewApp.relaunch_command(resume_index)


@pytest.mark.qt
def test_restart_from_source_reruns_the_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "argv", ["scraping_helper.py"])

    program, arguments = _relaunch_command(7)

    assert program == sys.executable
    assert arguments == ["scraping_helper.py", "--resume-index", "7"]


@pytest.mark.qt
def test_restart_of_a_macos_bundle_goes_through_launch_services(
    monkeypatch, tmp_path
):
    bundle = tmp_path / "DocumentReviewTool.app"
    monkeypatch.setattr(paths, "macos_bundle", lambda: bundle)
    monkeypatch.setattr(sys, "argv", ["DocumentReviewTool", "--resume-index", "3"])

    program, arguments = _relaunch_command(9)

    assert program == "open"
    assert arguments == ["-n", "-a", str(bundle), "--args", "--resume-index", "9"]


@pytest.mark.qt
def test_restart_does_not_accumulate_resume_flags(monkeypatch, tmp_path):
    bundle = tmp_path / "DocumentReviewTool.app"
    monkeypatch.setattr(paths, "macos_bundle", lambda: bundle)
    monkeypatch.setattr(
        sys, "argv", ["DocumentReviewTool", "--resume-index=2", "--resume-index", "4"]
    )

    _, arguments = _relaunch_command(11)

    assert arguments.count("--resume-index") == 1


def test_registration_makes_a_seeded_scraper_usable(monkeypatch, tmp_path):
    """A copied file is inert until it is in the registry the loader consults."""
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    settings = {}

    changed = starter_plugins.register(settings, starter_plugins.seed(settings))

    assert changed is True
    assert settings["defaultScraper"] == "text_scraper"
    registered = settings["scrapingTools"]["text_scraper"]
    assert registered["path"] == str(tmp_path / "scrapers" / "text_scraper.py")
    # No format codes: a fallback, not a tool bound to one document layout.
    assert registered["format_types"] == []


def test_registration_leaves_a_configured_installation_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    mine = {"path": "/somewhere/mine.py", "format_types": ["3"]}
    settings = {"scrapingTools": {"mine": mine}, "defaultScraper": "mine"}

    starter_plugins.register(settings, starter_plugins.seed(settings))

    assert settings["scrapingTools"] == {"mine": mine}
    assert settings["defaultScraper"] == "mine"


def test_registration_respects_a_chosen_default_with_an_empty_registry(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    settings = {"scrapingTools": {}, "defaultScraper": "something_i_removed"}

    starter_plugins.register(settings, starter_plugins.seed(settings))

    assert settings["defaultScraper"] == "something_i_removed"


def test_registration_does_nothing_when_nothing_was_seeded(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "portable_dir", lambda: tmp_path)
    settings = {}

    assert starter_plugins.register(settings, {}) is False
    assert settings == {}
