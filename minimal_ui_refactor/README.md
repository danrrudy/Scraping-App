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

## Requirements

- **Python 3.10 or newer** (developed on 3.13). The code uses `X | Y` type
  syntax, which 3.9 cannot parse.
- A desktop environment. This is a Qt application, not a command-line tool.

## Installation

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
python scraping_helper.py
```

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
| **Editable MID columns** | The fields that appear in the left sidebar. |

X and Y are optional, and *may themselves be editable fields* — that is how you
assign identifiers while reading a document rather than knowing them in
advance. You can type a column name that the sheet does not have yet; it is
created on load.

> The one restriction: if you configure **no** filename column, the X/Y pair is
> used to compose the filename instead, and then it cannot be editable —
> editing it would repoint the row at a different file.

### 5. Add a scraper

The application does not read PDFs by itself. A scraper is a small Python file
you supply; see [Writing a scraper](#writing-a-scraper) below. Press **Set Up
Scraping Tools**, add your file, and set it as the default.

Without one you will see *"No scraper found for format type -1"* in the log and
an empty content panel — the pages still display, but nothing is extracted.

### 6. Restart

Changing the MID columns, checkboxes, or field buttons rebuilds the sidebar,
which happens at startup. Settings will tell you a restart is needed; press
**Restart** at the top of the control panel. It reopens on the same row.

---

## The window

### Left sidebar — what you are recording

- **Information**: which entry you are on, the document, which observation
  within that document, the current page.
- **Fields**: one box per editable column, plus the classification scheme,
  status options, checkboxes, and notes.
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
- **Dev** — adds the MID audit, row restrictions, and result export.
- **Reviewer** — adds Accept/Reject and reviewer notes; hides row editing.

### Checkboxes — *Configure Checkboxes*

Each checkbox writes true/false to a MID column. Only the column is required:

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

Formulas may use the editable field names, numbers, `+ - * / // % **`, and
`abs` / `min` / `max` / `round`. Nothing else — no attribute access, no other
function calls. The dialog validates as you type and lists the names available.

Field names become identifiers: a column called `Total Cost` is written
`Total_Cost` in a formula. Values are read leniently, so `$1,234,567.00`,
`12%`, and accounting negatives like `(500)` all work. If an input is empty the
button says so in the status bar and leaves the target alone.

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

### Classification schemes — *Modify Classes*

A named set of status options (for example `Met`, `Not Met`, `Partially Met`)
shown as radio buttons. Select one with `Ctrl+1`…`Ctrl+9`, clear with `0`.

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
| `no_status` / `no_t/a` | rows missing a status, or missing target and actual |
| a test name | rows failing that test in the last audit |
| `none` | clears the restriction |

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
| `Ctrl+1` – `Ctrl+9` | Select the *n*th status option |
| `0` | Clear the status selection |
| `Ctrl+F` | Flag for review (a checkbox's own shortcut) |
| `Ctrl+N` | Add an observation from this document |
| `Ctrl+S` | Save the MID |
| `Ctrl+R` | Restart |
| `F1` – `F4` | Add a row at that hierarchy level (legacy schemas only) |

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
├── <your PDFs>
├── accepted/           text from accepted scrapes
│   └── formatted/
└── rejected/           text from rejected scrapes

logs/                   application logs and audit reports
user_settings.json      all configuration
```

These directories are created on first run. Exported text is named after the
document and identifiers — `annual-report-2024__DOJ__2024_full.txt` — so
several observations from one file do not overwrite each other.

---

## Troubleshooting

**"MID is missing required column(s)"** — the sheet has no column matching the
document filename role. Check the spelling in Configure MID Columns.

**"Every MID row must name a document"** — some rows have that column blank.
The row number in the message is the spreadsheet row.

**"No scraper found for format type -1"** — no scraper is configured, or none
matches this row's format code and no default is set.

**"PDF not found for MID row"** — the filename in the sheet does not match a
file in the data directory. Names are matched exactly, then with `-` replaced
by `_`.

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

At the time of writing: 189 pass, 4 fail. The four are long-standing and
unrelated to the current UI work — two concern the audit report's shape and two
are `MIDManager` expectations marked strict-xfail that now pass.

The architecture, the module boundaries, and the reasoning behind the recent
changes are documented in [REFACTOR_NOTES.md](REFACTOR_NOTES.md). In short:

| Module | Responsibility |
| --- | --- |
| `scraping_helper.py` | The controller: state, navigation, MID edits, file output |
| `ui/` | Every widget. The controller holds no widget references |
| `mid_schema.py` | Which column plays which role |
| `mid_manager.py` | Loading, restricting and mutating the spreadsheet |
| `document_session.py` | One open PDF and its scrape, shared by every row about it |
| `field_formula.py` | The formula language used by field buttons |
| `module_settings.py` | Settings a module declares for itself |

To add a content panel, subclass `ContentPanel`, decorate it with
`@register_panel`, and it appears in the View menu. To give it settings,
declare a `MODULE_SETTINGS` block and register that too.
