# Packaging and distribution

How the Document Review Tool becomes something you can hand to someone who
does not have Python.

---

## What a build contains

A **folder build**: an executable next to an `_internal` directory holding
Python, Qt, and the libraries. About **195 MB** on Windows. On macOS the same
folder is wrapped as `DocumentReviewTool.app`.

Not a single-file build. A single file unpacks itself to a fresh temporary
directory on every launch, which is slow with Qt and — more importantly —
would put the program somewhere different each run. The portable file layout
below depends on that not happening.

### The dependency line

Bundled: **PyQt5, PyMuPDF, pandas, Pillow, openpyxl, XlsxWriter**.

Deliberately excluded: **PyTorch, Transformers, Tesseract**. These are what
`table_scraper.py` and `table_scraper_lite.py` need, and they would take the
build from 195 MB to roughly 2.5 GB — and the Transformers models still
download from the network on first use, so bundling them does not even buy an
offline install.

The consequence: **the table-detection scrapers do not work in a packaged
build.** They remain available to anyone running from source. Every other
scraper — anything built on PyMuPDF, Pillow or the standard library — works in
both.

`DocumentReviewTool.spec` enforces this with an `excludes` list. If you ever
see the build size jump, something has pulled one of those back in.

---

## Where the application keeps its files

**Beside the program**, not in a hidden per-user folder. Copy the installation
folder to another machine, a shared drive, or a USB stick and the settings,
logs, and plugins travel with it.

```
DocumentReviewTool/          <- Windows: the folder you unzip
├── DocumentReviewTool.exe
├── _internal/               <- the program. Do not put your files here.
├── user_settings.json       <- created on first run
├── logs/
├── scrapers/
├── extractors/
└── data/
```

On macOS "beside the program" means beside the `.app`, not inside it — a signed
bundle is read-only:

```
DocumentReviewTool.app
user_settings.json
logs/  scrapers/  extractors/  data/
```

`paths.py` works this out. Nothing else should derive a writable path from
`__file__`.

### If that location is not writable

Dropped in `Program Files`, or run from a read-only disk image, there is
nowhere portable to write. Rather than fail to start, the application falls
back to the conventional per-user directory:

| Platform | Fallback |
| --- | --- |
| Windows | `%LOCALAPPDATA%\DocumentReviewTool` |
| macOS | `~/Library/Application Support/DocumentReviewTool` |
| Linux | `~/.local/share/DocumentReviewTool` |

The first line of every log says which of the two is in use. If a user reports
that their settings vanished, read that line first — it usually means they
installed somewhere they cannot write to.

### First run

The starter plugins shipped inside the build (`bundled/`) are copied out into
`scrapers/` and `extractors/`, and registered as the defaults — but **only into
empty folders, and only when nothing is configured yet**. A folder that already
holds plugins belongs to the user; a file they edited stays edited, and a file
they deleted stays deleted.

---

## Building

### Use a clean virtual environment

Not optional. PyInstaller bundles whatever it finds installed, so a global
interpreter with unrelated packages produces a larger and less predictable
build.

> **Known snag on this machine:** the global Python 3.13 has the obsolete
> `pathlib` PyPI backport installed, and PyInstaller refuses to run while it is
> present. A virtual environment sidesteps it. To fix it globally instead:
> `python -m pip uninstall pathlib` — that package has been dead since 2014 and
> only shadows the standard library.

### Windows

```bash
python -m venv .venv-build
```

```bash
.venv-build\Scripts\pip install -r requirements.txt -r requirements-build.txt
```

```bash
.venv-build\Scripts\pyinstaller --noconfirm --clean DocumentReviewTool.spec
```

The result is `dist/DocumentReviewTool/`. Zip that folder to distribute it.

**Keep `--clean`.** Without it PyInstaller reuses a cached analysis and will
happily produce a build running your *previous* source. This is easy to miss,
because the build succeeds and the app runs — it is just the wrong code.

### macOS

Same three steps with `source .venv-build/bin/activate`, then sign the bundle
(see below). The result is `dist/DocumentReviewTool.app`.

Archive it with `ditto`, never a plain zip — a plain zip flattens the symlinks
and permission bits inside a `.app` and the copy will not launch:

```bash
ditto -c -k --sequesterRsrc --keepParent dist/DocumentReviewTool.app DocumentReviewTool-macos.zip
```

### You cannot build the Mac app on Windows

PyInstaller does not cross-compile. It bundles the interpreter and libraries of
the machine it runs on. A macOS build requires macOS — either a Mac, or the CI
workflow below.

PyQt5 also publishes **separate `arm64` and `x86_64` wheels** rather than a
universal one, so each Mac build is single-architecture. Apple Silicon can run
an x86_64 build under Rosetta, but not the reverse.

---

## Continuous integration

`.github/workflows/build.yml` runs the tests on Linux, then builds three
targets in parallel:

| Runner | Produces |
| --- | --- |
| `windows-latest` | `DocumentReviewTool-windows-x64.zip` |
| `macos-14` | `DocumentReviewTool-macos-arm64.zip` (Apple Silicon) |
| `macos-13` | `DocumentReviewTool-macos-x86_64.zip` (Intel) |

Every run uploads them as workflow artifacts, kept for 90 days. Pushing a tag
matching `v*` additionally attaches them to a GitHub release, which is the
better way to hand a build to someone outside the project — release downloads
need no GitHub account, artifact downloads do.

The remote is `github.com/danrrudy/Scraping-App`, so pushing any branch starts
a build.

The test job deliberately deselects the four long-standing failures listed at
the bottom of this file. It stays a real gate — any *other* failure stops the
build before anything is packaged. Delete a `--deselect` line as each is fixed.

To cut a release: bump `__version__` in `version.py`, commit, then

```bash
git tag v1.1.0 && git push origin v1.1.0
```

---

## macOS code signing

The build is **ad-hoc signed** (`codesign --sign -`). That costs nothing and is
enough to make the app launchable on Apple Silicon, where a completely unsigned
bundle is refused outright.

It is *not* notarised, so Gatekeeper still quarantines it on first open. Tell
your users one of these:

**Right-click to open.** In Finder, right-click (or Control-click)
`DocumentReviewTool.app`, choose **Open**, then **Open** again in the dialog.
Only needed once.

**Or, if macOS says the app "is damaged and can't be opened"** — which is what
it says about a quarantined download, misleadingly — clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine /path/to/DocumentReviewTool.app
```

### If you want a clean double-click install

That needs an **Apple Developer Program** membership (99 USD/year) and
notarisation. The steps, once you have a Developer ID certificate:

1. Add the certificate and an app-specific password to the repository secrets.
2. In the workflow, replace `--sign -` with `--sign "Developer ID Application: Your Name (TEAMID)"`
   and add `--options runtime` for the hardened runtime.
3. Submit the archive with `xcrun notarytool submit --wait`, then
   `xcrun stapler staple dist/DocumentReviewTool.app`.

Worth it if the audience is beyond a handful of colleagues; overkill if not.

---

## Checklist before shipping a build

- [ ] `python -m pytest` passes (four failures predate this work — see below).
- [ ] The build folder is around 195 MB, not gigabytes. A jump means an
      excluded dependency crept back in.
- [ ] Unzip somewhere fresh and launch it. `user_settings.json`, `logs/`,
      `scrapers/` and `extractors/` should appear beside the executable.
- [ ] The first log line names the version; the second says `(portable)`.
- [ ] Point it at a real MID and confirm a document opens.

### Known pre-existing test failures

Four tests fail on `main` and still fail here; none are packaging-related:

- `test_audit_runner.py::test_audit_writes_detailed_and_summary_reports`
- `test_audit_runner.py::test_audit_records_missing_pdf_as_fatal_failure`
- `test_mid_manager.py::test_direct_navigation_can_select_first_row`
- `test_mid_manager.py::test_propagated_flag_is_persistent_in_master_dataframe`

The last two are `XPASS(strict)` — they describe bugs that have since been
fixed, so the expectation of failure is now wrong.
