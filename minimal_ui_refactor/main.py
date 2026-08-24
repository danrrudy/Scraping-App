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
from PyQt5.QtWidgets import QApplication

import paths
import starter_plugins
from app_settings import load_settings, save_settings
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


def prepare_installation():
    """First-run housekeeping, and a log line saying where files are going."""
    logger = setup_logger()
    logger.info(f"{APP_NAME} {__version__} starting")
    logger.info(paths.location_note())

    settings = load_settings()
    written = starter_plugins.seed(settings, logger)
    if starter_plugins.register(settings, written, logger):
        # Saved here rather than left in memory: the window loads the settings
        # again for itself, and would otherwise not see the registration.
        save_settings(settings)

    return logger


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    configure_qt()
    application = build_application(argv)
    prepare_installation()

    # Imported after the settings and plugin folders are in place, and after
    # QApplication exists: constructing the window puts dialogs on screen.
    from scraping_helper import TextScrapingReviewApp

    window = TextScrapingReviewApp()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())
