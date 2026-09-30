# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build description for the Document Review Tool.

Build from this directory:

    pyinstaller --noconfirm DocumentReviewTool.spec

Produces a folder build (``dist/DocumentReviewTool/``) on Windows and Linux,
and additionally a ``.app`` bundle on macOS. A folder build rather than a
single file, because a single-file build unpacks itself to a temporary
directory on every launch — slow with Qt, and it would put the program
somewhere different each run, which the portable file layout depends on not
happening.

Scope: the *lite* dependency set — Qt, PyMuPDF, pandas, Pillow, openpyxl. The
table-detection scrapers need PyTorch, Transformers and Tesseract; those are
deliberately excluded here and stay available to people running from source.
See PACKAGING.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).resolve()))

from version import APP_SLUG, BUNDLE_ID, __version__

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# Read-only files that ship inside the build. The starter plugins are copied
# out beside the program on first run; see starter_plugins.py.
datas = [("bundled", "bundled")]

# Loaded by name at run time rather than imported, so PyInstaller cannot see
# them by following imports.
hiddenimports = [
    "openpyxl",
    "openpyxl.cell._writer",
    "xlsxwriter",
    "pandas._libs.tslibs.base",
]

# Machine-learning and plotting stacks that pandas, Pillow or a stray import
# can drag in. Excluding them is the difference between a ~300 MB build and a
# ~2.5 GB one.
excludes = [
    "torch",
    "torchvision",
    "transformers",
    "tensorflow",
    "pytesseract",
    "scipy",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
    "sklearn",
    "tkinter",
    "test",
    "pytest",
    "setuptools",
    "pip",
]

# Qt ships far more than this application uses. Each of these is tens of
# megabytes of shared library that would otherwise be copied in.
excludes += [
    "PyQt5.QtWebEngine",
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebKit",
    "PyQt5.QtWebKitWidgets",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuick3D",
    "PyQt5.QtQuickWidgets",
    "PyQt5.Qt3DCore",
    "PyQt5.Qt3DRender",
    "PyQt5.QtBluetooth",
    "PyQt5.QtNfc",
    "PyQt5.QtLocation",
    "PyQt5.QtPositioning",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSensors",
    "PyQt5.QtSerialPort",
    "PyQt5.QtSql",
    "PyQt5.QtTest",
    "PyQt5.QtDesigner",
    "PyQt5.QtHelp",
    "PyQt5.QtXmlPatterns",
]


analysis = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_SLUG,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A desktop application: no console window should appear behind it on
    # Windows. Diagnostics go to the log files instead.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_SLUG,
)

if IS_MACOS:
    app = BUNDLE(
        collection,
        name=f"{APP_SLUG}.app",
        icon=None,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            # Without this the window renders at a quarter size on a Retina
            # display, whatever Qt is told.
            "NSHighResolutionCapable": True,
            # A document-review tool with a window, not a background agent.
            "LSBackgroundOnly": False,
            "LSMinimumSystemVersion": "11.0",
        },
    )
