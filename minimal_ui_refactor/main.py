"""Launcher for the Document Review Tool.

Everything here has to happen before the application itself exists:

* Qt's high-DPI attributes must be set before the first ``QApplication`` is
  constructed, or a 150%-scaled Windows display renders the window blurry and
  a Retina Mac renders it at a quarter size.
* The starter plugins have to be on disk before the window asks the settings
  which scraper to use.

Running from source, ``python main.py`` and ``python scraping_helper.py`` both
arrive here. A packaged build has this module as its entry point.
"""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

import paths
import starter_plugins
from app_settings import (
    load_settings,
    migrate_settings,
    save_settings,
    settings_version_mismatch,
    stamp_settings_version,
)
from logger import setup_logger
from version import APP_NAME, APP_SLUG, __version__


def configure_qt():
    """Qt attributes that only take effect before ``QApplication`` exists."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def build_application(argv):
    application = QApplication(list(argv))
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationName(APP_SLUG)
    return application


def confirm_settings_version(settings, logger, ask=None) -> bool:
    """Warn when the settings file came from another version. Returns whether to go on.

    A file written by a different release may configure things this one
    reads differently, so the user is told and asked before the program
    carries on with it. Going ahead re-stamps the file, so the question is
    asked once per upgrade rather than at every start. ``ask`` is the
    question function, replaceable for tests.
    """
    mismatch = settings_version_mismatch(settings)
    if mismatch is None:
        return True
    stored, current = mismatch
    logger.warning(f"Settings file was written by {stored}; this is {current}")

    ask = ask or QMessageBox.question
    choice = ask(
        None,
        "Settings From Another Version",
        f"The settings file was last saved by {stored} of {APP_NAME}, and "
        f"this is version {current}.\n\n"
        "Settings that changed between versions may be read differently or "
        "ignored. Check them under Settings after opening.\n\n"
        "Continue with these settings?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if choice != QMessageBox.Yes:
        logger.info("User declined to continue with settings from another version")
        return False

    stamp_settings_version(settings)
    save_settings(settings)
    logger.info(f"Settings file re-stamped as version {current}")
    return True


def prepare_installation():
    """First-run housekeeping, and a log line saying where files are going.

    Returns ``None`` when the program should not go on: the user was shown
    that the settings came from another version and chose to stop.
    """
    logger = setup_logger()
    logger.info(f"{APP_NAME} {__version__} starting")
    logger.info(paths.location_note())

    settings = load_settings()
    if not confirm_settings_version(settings, logger):
        return None
    # Before anything reads module settings: resolving a module drops keys it
    # no longer declares, so a renamed setting has to be carried across while
    # the old key is still in the file.
    migrated = migrate_settings(settings)
    if migrated:
        logger.info("Brought stored settings up to date")

    written = starter_plugins.seed(settings, logger)
    if starter_plugins.register(settings, written, logger) or migrated:
        # Saved here rather than left in memory: the window loads the settings
        # again for itself, and would otherwise not see the registration.
        save_settings(settings)

    return logger


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    configure_qt()
    application = build_application(argv)
    if prepare_installation() is None:
        return 0

    # Imported after the settings and plugin folders are in place, and after
    # QApplication exists: constructing the window puts dialogs on screen.
    from scraping_helper import TextScrapingReviewApp

    window = TextScrapingReviewApp()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())
