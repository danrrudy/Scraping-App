"""The one place the application's identity is written down.

Read by the launcher, by the PyInstaller spec that names the build, and by the
release workflow that names the artifacts. Change it here and everything
downstream follows.
"""

__version__ = "1.1.0"

#: What the window, the executable, and the macOS bundle are called.
APP_NAME = "Document Review Tool"

#: The same name with no spaces, for filenames and bundle identifiers.
APP_SLUG = "DocumentReviewTool"

#: Reverse-DNS identifier macOS requires of an application bundle.
BUNDLE_ID = "edu.research.documentreviewtool"
