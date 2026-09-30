# Document Review Tool

A desktop application for reading values out of a folder of PDFs and recording
them, one row at a time, into a spreadsheet.

You supply a spreadsheet — the **Master Input Document**, or MID — in which
each row names a document. The application opens that document, runs a
**scraper** over it, and puts the result beside the page so you can highlight
what you need and send it into the fields you are filling in. Your edits go
back into the spreadsheet, which you export when you are done.

Nothing about the domain is built in. The column names, the fields you edit,
the checkboxes, the calculator buttons, and the tool that reads the PDFs are
all configuration.

```
┌────────────────┬─────────────────────┬────────────────────┐
│  left sidebar  │    document view    │   content panel    │
│                │                     │                    │
│  the fields    │  the page you are   │  what the scraper  │
│  you fill in,  │  looking at         │  found — select    │
│  and controls  │                     │  and send it left  │
└────────────────┴─────────────────────┴────────────────────┘
```

---

## Installing

Two ways in. Most people want the first.

### A packaged build — no Python needed

Download the archive for your platform, unzip it **somewhere you can write
to** (your Desktop or Documents, not `Program Files`), and run it.

- **Windows** — unzip and run `DocumentReviewTool.exe`.
- **macOS** — unzip, then **right-click** `DocumentReviewTool.app` and
  choose **Open**, then **Open** again. Only the first launch needs this; the
  app is signed but not notarised, so a plain double-click is refused.

Everything the application writes — your settings, logs, scrapers, and
data — lives **beside the program**, so you can move the whole folder to
another machine and it keeps working. See [PACKAGING.md](PACKAGING.md) for the
details, including what happens if you install somewhere read-only.

One limitation: the table-detection scrapers need PyTorch and Tesseract, which
are not in the build. Everything else works. Run from source if you need them.

### From source

- **Python 3.10 or newer** (developed on 3.13). The code uses `X | Y` type
  syntax, which 3.9 cannot parse.
- A desktop environment. This is a Qt application, not a command-line tool.

```bash
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
on macOS/Linux — then:

```bash
pip install -r requirements.txt
```

That installs PyQt5, pandas, PyMuPDF, Pillow, openpyxl and XlsxWriter. A
scraper plugin may need more (OCR, table detection, ML models); install those
when you add the plugin.

## Running

```bash
python main.py
```

`python scraping_helper.py` still works and does the same thing.

---

## First run

The first launch creates `user_settings.json` from defaults and warns that no
MID is configured. That is expected. Work through the following once.

### 1. Prepare a folder of documents

Put your PDFs in one directory. The application never searches subfolders — it
looks for each row's document directly in the data directory you configure.

### 2. Prepare the spreadsheet

An `.xlsx` or `.csv` with **one row per observation** you intend to record.

The only column that must exist is the one naming each row's document:

| Filename                  |
| ------------------------- |
| annual-report-2024.pdf    |
| annual-report-2024.pdf    |
| quarterly-summary.pdf     |

That is a complete, working MID. Two rows may name the same file — one
document often carries several observations.

Every other column you configure is **created automatically** if the sheet does
not have it, so you can add the fields you want to fill in without touching the
spreadsheet first. If a filename has no extension, `.pdf` is assumed.

### 3. Point the application at both

Press **Settings**, then:

- **Master Input Document** — browse to the spreadsheet. You will be asked
  which sheet to use.
- **dataDirectory** — the folder holding the PDFs.
- **logFileDirectory** — where log files go.

### 4. Describe the columns

Still in Settings, press **Configure MID Columns**.

| Role | Meaning |
| --- | --- |
| **Document filename** | The anchor. Which file this row is about. |
| X / Y identifier | Optional labels for the observation, e.g. Agency and Year. |
| PDF page reference | Optional. Which pages to read — `3`, `4-9`, `2, 5-7`. Leave unset to use the whole document. |
| Format code | Optional. An integer choosing which scraper to use. |
| Search keyword | Optional. Used by the audit only. |
| Entry label | How each row is named on screen and in the logs. |

A fresh installation expects only a `Filename` column, which is what
**Generate Empty MID…** writes. Everything else here is optional.

X and Y are optional, and *may themselves be editable fields* — that is how you
assign identifiers while reading a document rather than knowing them in
advance. You can type a column name that the sheet does not have yet; it is
created on load.

> The one restriction: if you configure **no** filename column, the X/Y pair is
> used to compose the filename instead, and then it cannot be editable —
> editing it would repoint the row at a different file.

**Entry label** chooses how a row is named wherever the application refers to
one — the status bar, the log, the audit report. Pick from `X — Y` (the
default), `X (Y)`, `X Y`, `XY`, `Y — X`, `Filename`, or `Filename (X — Y)`. The
dialog previews your choice against the columns you selected. A blank
identifier is dropped rather than leaving a stray separator, and a row with no
identifiers at all falls back to its filename.

### 5. Add the fields

Press **Configure Fields** to say which columns you will fill in. Each field
is one MID column, shown in the left sidebar in the order listed; a column the
sheet lacks is created on load. See [Fields](#fields--configure-fields) below
for lists, radio buttons, and nested hierarchies.

### 6. Add a scraper

The application does not read PDFs by itself; a scraper is a small Python file
that does it. A first run installs `text_scraper.py` into `scrapers/` and makes
it the default, so plain text extraction works out of the box.

To use your own instead — see [Writing a scraper](#writing-a-scraper)
below — press **Set Up Scraping Tools**, add your file, and set it as the
default.

If you ever see *"No scraper found for format type -1"* in the log and an empty
content panel, no scraper is registered: — the pages still display, but nothing is extracted.

### 7. Restart

Changing the MID columns, fields, checkboxes, or field buttons rebuilds the sidebar,
which happens at startup. Settings will tell you a restart is needed; press
**Restart** at the top of the control panel. It reopens on the same row.

---

## The window

### Left sidebar — what you are recording

- **Information**: which entry you are on, the document, which observation
  within that document, the current page.
- **Fields**: one editor per configured column — a text box, a dropdown, or a
  row of radio buttons — plus the checkboxes and notes.
- **Controls**: navigation, settings, and the mode-specific tools.

An amber banner appears here when something needs attention — for example when
another row records the same document and identifiers.

### Document view — the page

The rendered PDF page. **Left-click turns it 90° clockwise, right-click 90°
counter-clockwise**, which is how you deal with landscape scans. Rotation can
be switched off, and can be made to persist across pages, in Module Settings.

Table-shaped scrapes appear here as a zoomable image instead.

### Content panel — what the scraper found

Swappable, chosen from the **View** menu. Two ship with the application:

- **Scraped Text** — the page text, with your field values highlighted
  wherever they appear in it.
- **Rendered Table** — HTML, for table-shaped results.

Select text here and send it into a field by pressing its number key, or by
right-clicking and choosing **Send Selection To**.

---

## Configuring it for your work

Everything below lives in Settings and is stored in `user_settings.json`.

### Modes

`User`, `Dev`, and `Reviewer` show different controls.

- **User** — the fields, navigation, add/delete rows.
- **Dev** — adds the MID audit and audit-based row restrictions.
- **Reviewer** — adds Accept/Reject and reviewer notes; hides row editing.

### Fields — *Configure Fields*

Each field edits one MID column. Only the column is required:

```json
{"column": "status", "label": "Status", "kind": "radio",
 "options": ["Met", "Not Met", "Partially Met"]}
```

- **Edited as** — `text` (a box you type or transfer into), `dropdown`, or
  `radio`. The last two take an options list and cannot receive a
  transferred selection; the number keys skip them.
- **Hierarchy level** — marks the field as one level of a nested structure,
  ordered the way the fields are listed (say *objective → goal → metric*). It
  gets a **+** button that adds a new row beneath the current one, keeping the
  levels above and clearing this one and those beneath, so you only fill in
  what is new. Give the button a **shortcut** (`F2`, `Ctrl+G`, …) if you use it
  a lot.

When both X and Y are configured and at least one field is a hierarchy level,
**Copy Previous Year** appears: it rebuilds the current X/Y block from the
rows with the same X and a Y one less, copying their hierarchy fields.

### Checkboxes — *Configure Checkboxes*

Each checkbox writes true/false to a MID column. Only the column is required.
The only one built in is **Flag for review** (`_flag`, `Ctrl+F`); the rest are
yours to define:

```json
{"column": "_verified", "label": "Verified", "shortcut": "Ctrl+V",
 "message": "Marked verified",
 "counter": {"column": "weeks_elapsed", "label": "Weeks:", "maximum": 52}}
```

`counter` adds a number box beside the checkbox that is only editable while the
box is ticked, and blanks itself when unticked. Columns that the MID lacks are
created on load.

### Field buttons — *Configure Field Buttons*

Buttons that compute one field from the others. They appear next to the field
they write into.

```json
{"label": "10%", "target": "Match", "expression": "Total_Cost * 0.10",
 "decimals": 2}
```

Field names become identifiers: a column called `Total Cost` is written
`Total_Cost` in a formula. The dialog validates as you type and lists the names
available.

**Number formulas** use `+ - * / // % **` and `abs` / `min` / `max` / `round`.
Values are read leniently, so `$1,234,567.00`, `12%`, and accounting negatives
like `(500)` all work. `decimals` sets how the result is rounded when written.

**Text formulas** join and reshape what was scraped. `&` joins pieces together,
exactly as in a spreadsheet, and these functions are available:

| Function | Does | Example result |
| --- | --- | --- |
| `concat(a, b, …)` | joins, same as `&` | `concat(Gov, " FY", FY)` → `Ann Arbor FY2024` |
| `lower` / `upper` | case | `upper(Gov)` → `ANN ARBOR` |
| `title` | Capitalises Every Word | `title(Gov)` → `Ann Arbor` |
| `sentence` | Capitalises the first word only | `sentence(Gov)` → `Ann arbor` |
| `camel` / `pascal` | `camelCase` / `PascalCase` | `camel(Gov)` → `annArbor` |
| `snake` / `kebab` | `snake_case` / `kebab-case` | `snake(Gov)` → `ann_arbor` |
| `trim` | drops surrounding spaces | `trim(Gov)` |
| `replace(text, old, new)` | swaps every occurrence | `replace(Notes, ",", "-")` |

```json
{"label": "Slug", "target": "Key", "expression": "snake(Gov & \" \" & FY)"}
```

`+` always means arithmetic, even between two pieces of text, so a formula
never changes meaning because a scraped field happened to hold digits — write
`&` when you mean *join*. A text result is written exactly as the formula
produces it; `decimals` applies only to numbers.

**Setting a checkbox too.** A button may tick one of the sidebar checkboxes in
the same press — *Also sets* names the checkbox and *Checkbox action* is
`check`, `uncheck`, or `toggle`:

```json
{"label": "Sum", "target": "Total_Exp",
 "expression": "LMIG_Exp + Match + Local_Exp", "decimals": 0,
 "checkbox": "_aggregate", "checkbox_action": "check"}
```

`checkbox` may name the checkbox by its MID column (`_aggregate`) or by its key
(`aggregate`). The checkbox behaves as if you clicked it, so its counter wakes
up with it.

Nothing else is permitted in a formula — no attribute access, no other function
calls. If an input is empty the button says so in the status bar and leaves
both the target field and the linked checkbox alone.

### Module settings — *Module Settings*

The document view and each content panel define their own settings, shown one
tab per module:

| Module | Settings |
| --- | --- |
| Document Viewer | click-to-rotate; keep rotation between pages |
| Scraped Text Panel | number-key transfer and how many keys; right-click transfer menu; highlighting |
| Rendered Table Panel | follow links |

Outside Dev mode you see only the modules currently loaded; in Dev mode you see
every module, including ones not on screen. Settings for modules you have used
before are kept in the file even while they are not loaded.

> Turning off **number-key transfer** frees the digit keys, which is what you
> want if your fields hold numbers you need to type.

### Settings from another version

`user_settings.json` is stamped with the version that wrote it. When a newer
(or older) build opens a file from a different version it says so and asks
whether to continue. Continuing re-stamps the file, so you are asked once per
upgrade; declining closes the program without touching anything. Settings a
version no longer knows are ignored with a console warning rather than
breaking start-up.

---

## Working through a MID

**Navigate** with `< Entry` / `Entry >` and `< Page` / `Page >`, or jump to a
specific row with `Ctrl+O`.

**Fill fields** by selecting text in the content panel and pressing `1`–`4`, or
by typing. `Tab` and `Shift+Tab` move between fields.

**Several observations in one document** — press **Add Observation from this
Document** (`Ctrl+N`). It copies the current row, keeps the filename, clears
the fields, and starts on the page you are looking at. The document stays open,
so this is instant. The sidebar shows *"Observation 2 of 3 in this document"*.

**Save** with **File → Save MID…** (`Ctrl+S`), which writes the whole
spreadsheet to `.xlsx` or `.csv`. Edits live in memory until you do —
the application never writes over your original.

### Which rows have you done?

Rows you have actually changed are tracked, so a long MID can be worked
through in more than one sitting.

*Navigating past a row does not count as editing it.* The sidebar is committed
on every move, but nothing is written unless you changed something and that
change differs from what the row already holds. Typing, ticking a checkbox,
picking a list option, pressing a field button, and turning to a different page
all count; simply looking at a row does not.

The first time a change to a row is saved, that row is marked **edited** in an
`_edited` column. It is written out with the rest of the MID, so reopening a
saved sheet picks up where you left off.

**File → Go to First Unedited Entry** (`Ctrl+U`) jumps to the topmost row that
has never been edited, committing whatever you were working on first. The
status bar reports how many unedited rows are left in the current view; when
there are none it says so.

**File → Entry → Mark as Edited** shows the current row's flag and lets you set
it by hand — useful for a row you deliberately want to leave as it is, or one
you want to come back to. It is a checkbox, so it un-marks as well.

**Restart** (`Ctrl+R`) relaunches and returns to the row you were on. If there
are unsaved changes it offers **Save**, **Discard**, or **Cancel**; backing out
of the save dialog abandons the restart rather than losing the work.

### Dev and Reviewer tools

**Restrict to:** narrows the view to rows worth attention, then press **Load
Cases**:

| Choice | Rows shown |
| --- | --- |
| `same_document` | every row about the file you are on |
| `duplicate_observation` | rows sharing a document and identifiers with another row |
| `_flag` | rows flagged for review |
| `_gen` | rows the application added (Reviewer) |
| `rejected` | rows a reviewer rejected (Reviewer) |
| a test name | rows failing that test in the last audit (Dev) |
| `none` | clears the restriction |

In Reviewer mode, **Accept** and **Reject** record a verdict in
`reviewer_status` and move to the next row; rejecting also flags the row.

**Run MID Audit** checks every row — is the PDF there, do the pages parse, did
text come out, do the field values actually appear in the document — and writes
a report to the log directory.

---

## Keyboard reference

| Key | Action |
| --- | --- |
| `1` – `4` | Send the selection to that field (configurable) |
| `Tab` / `Shift+Tab` | Next / previous field |
| `-` / `=` | Previous / next page |
| `Ctrl+←` / `Ctrl+→` | Previous / next MID entry |
| `Ctrl+Enter` | Next MID entry |
| `Ctrl+O` | Jump to a MID entry |
| `Ctrl+F` | Flag for review (a checkbox's own shortcut) |
| `Ctrl+N` | Add an observation from this document |
| `Ctrl+S` | Save the MID |
| `Ctrl+U` | Go to the first unedited entry |
| `Ctrl+R` | Restart |
| *as configured* | Add a row at a hierarchy level (a field's own **+** shortcut) |

---

## Writing a scraper

A scraper is one Python file defining a subclass of `BaseScraper`. It receives
the pages of one document and returns a dictionary.

```python
from base_scraper import BaseScraper


class PlainTextScraper(BaseScraper):
    """Reads the embedded text layer out of each page."""

    def scrape(self):
        self._output = {
            "method": type(self).__name__,   # must match the class name
            "format": "text",                # "text" or "image"
            "page": list(range(len(self.pages))),
            "text": [page.get_text() for page in self.pages],
        }
```

- `self.pages` is a list of `fitz.Page` objects.
- `format` decides how the result is shown. `"text"` needs `text` to be a list
  of strings, **one per page in order**. `"image"` instead needs
  `result` — a list, one entry per page, of table dictionaries carrying a PIL
  image under `table_image`.
- `method`, `page` and `text` are required by `BaseScraper`; leaving one out
  raises when the result is read.

Add the file through **Settings → Set Up Scraping Tools**. A scraper can be
bound to specific values of the Format code column, so different document
layouts get different tools; the default handles everything else.

Extractors — a second, later-stage plugin — work the same way through
`base_extractor.py` and **Set Up Extraction Tools**.

---

## Where things go

```
your-data-directory/
└── <your PDFs>

logs/                   application logs and audit reports
user_settings.json      all configuration, stamped with the version that wrote it
```

The data directory holds nothing but your documents; the application writes
its results into the MID you save, not beside the PDFs.

---

## Troubleshooting

**"MID is missing required column(s)"** — the sheet has no column matching the
document filename role. Check the spelling in Configure MID Columns.

**"Every MID row must name a document"** — some rows have that column blank.
The row number in the message is the spreadsheet row.

**"No scraper found for format type -1"** — no scraper is configured, or none
matches this row's format code and no default is set.

**"PDF not found for MID row"** — the filename in the sheet does not match a
file in the data directory. Names are matched exactly; a name with no
extension is tried as `.pdf`.

**Pages look blank, or only page 1 is reachable** — check the page reference
column. Leave it unconfigured to work through the whole document.

**Digits will not type into a field** — number-key transfer is bound to them.
Turn it off, or reduce its key count, in Module Settings.

The log directory holds the detail for all of these. Set `loggingLevel` to
`DEBUG` in Settings for more.

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite runs under a generic test schema declared in `tests/conftest.py`;
nothing in it depends on any particular project's column names.

**Branches.** `main` holds only the program as it is shipped. `dev` is where
work happens, and additionally carries a `legacy/` folder: the application's
first incarnation, kept for reference and not imported by anything. Merge
`dev` into `main`, not the other way round — `main` has deleted `legacy/`, so
merging `main` into `dev` would delete it there too.

To build a distributable executable, see [PACKAGING.md](PACKAGING.md).

The architecture, the module boundaries, and the reasoning behind the recent
changes are documented in [REFACTOR_NOTES.md](REFACTOR_NOTES.md). In short:

| Module | Responsibility |
| --- | --- |
| `scraping_helper.py` | The controller: state, navigation, MID edits, file output |
| `ui/` | Every widget. The controller holds no widget references |
| `mid_schema.py` | Which column plays which role, and how each field is edited |
| `mid_manager.py` | Loading, restricting and mutating the spreadsheet |
| `field_dialog.py` | The Configure Fields dialog |
| `document_session.py` | One open PDF and its scrape, shared by every row about it |
| `field_formula.py` | The formula language used by field buttons |
| `module_settings.py` | Settings a module declares for itself |
| `main.py` | The launcher: high-DPI setup and first-run housekeeping |
| `paths.py` | Where files live, in a checkout and in a packaged build |
| `starter_plugins.py` | The scrapers a fresh installation starts with |

To add a content panel, subclass `ContentPanel`, decorate it with
`@register_panel`, and it appears in the View menu. To give it settings,
declare a `MODULE_SETTINGS` block and register that too.
