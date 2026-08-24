"""Where the application's files live.

Two locations differ between a source checkout and a frozen build, and every
other module should ask this one rather than working them out from
``__file__``:

``resource_dir()``
    Read-only things that ship *with* the program — starter plugins, templates.
    In a frozen build these are unpacked somewhere PyInstaller chooses, and
    that place is not writable.
``app_dir()``
    The writable side: settings, logs, documents, and the user's own plugins.

The writable side is **portable**. It sits beside the program, not in a hidden
per-user folder, so the whole installation can be copied to another machine, a
shared drive, or a USB stick and carry its configuration with it. On macOS
"beside the program" means beside ``DocumentReviewTool.app``, not inside it —
the bundle's own contents are read-only once the app is signed.

If that location cannot be written to — the app was dropped in
``Program Files``, or opened from a read-only disk image — there is nowhere
portable to put anything, so we fall back to the conventional per-user
directory rather than failing to start. :func:`location_note` says which of the
two is in use, for the log.

This module deliberately imports nothing but the standard library: it is loaded
by :mod:`app_settings`, which runs before the logger exists.
"""

import os
import sys
from pathlib import Path

#: Folder name used under the per-user directory when portable mode is refused.
APP_NAME = "DocumentReviewTool"

_app_dir = None
_fallback_reason = ""


def resource_dir() -> Path:
    """The directory holding files that shipped with the program."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent


def is_frozen() -> bool:
    """True when running from a built executable rather than from source."""
    return bool(getattr(sys, "frozen", False))


def macos_bundle() -> Path | None:
    """The ``.app`` this program is running inside, if it is running in one."""
    if not is_frozen() or sys.platform != "darwin":
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def portable_dir() -> Path:
    """Where a portable installation keeps its files.

    Beside the executable, except on macOS, where beside the ``.app`` bundle is
    what a user would recognise as "next to the program".
    """
    if not is_frozen():
        return Path(__file__).resolve().parent

    bundle = macos_bundle()
    if bundle is not None:
        return bundle.parent
    return Path(sys.executable).resolve().parent


def user_data_dir() -> Path:
    """The conventional per-user location, used only when portable is refused."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / APP_NAME


def is_writable(directory) -> bool:
    """Whether we can actually create files in ``directory``.

    Asked by writing, not by inspecting permissions: on Windows the permission
    bits routinely disagree with what a write will do.
    """
    directory = Path(directory)
    probe = directory / ".write-test"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def app_dir() -> Path:
    """The writable directory this installation keeps its files in.

    Worked out once and remembered, so a directory that becomes unwritable
    mid-session cannot split the application's files across two places.
    """
    global _app_dir, _fallback_reason

    if _app_dir is not None:
        return _app_dir

    portable = portable_dir()
    if is_writable(portable):
        _app_dir = portable
        return _app_dir

    _fallback_reason = f"{portable} is not writable"
    fallback = user_data_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    _app_dir = fallback
    return _app_dir


def in_app_dir(*parts) -> str:
    """A path inside :func:`app_dir`, as a string.

    A string rather than a ``Path`` because it is what the settings file holds
    and what the rest of the application passes to :mod:`os.path`.
    """
    return str(app_dir().joinpath(*parts))


def location_note() -> str:
    """One line describing where files are going and why, for the log."""
    directory = app_dir()
    if _fallback_reason:
        return f"Using {directory} for application files ({_fallback_reason})"
    return f"Using {directory} for application files (portable)"


def reset_cache():
    """Forget the resolved location. For tests, which move the goalposts."""
    global _app_dir, _fallback_reason
    _app_dir = None
    _fallback_reason = ""
