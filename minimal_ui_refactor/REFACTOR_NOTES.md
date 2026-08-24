# UI Refactor

The application is being pulled apart into a UI layer and a controller. This
pass extracts the whole user interface into a `ui/` package built around three
panes, and removes every widget reference from `TextScrapingReviewApp`.

## The three panes

```
+----------------+---------------------+--------------------+
|  left sidebar  |    document view    |   content panel    |
|  all controls  |  what you're on     |  what you do with  |
|  and fields    |                     |  it (swappable)    |
+----------------+---------------------+--------------------+
```

| Module | Owns |
| --- | --- |
| `ui/left_sidebar.py` | `LeftSidebar` — info block, editable fields, every control |
| `ui/document_view.py` | `DocumentView` — page render and the clickable image canvas |
| `ui/panels/` | `ContentPanel` interface plus the registered right-hand panels |
| `ui/main_window.py` | `MainWindowUI` — assembles the three, exposes the façade |
| `ui/context.py` | `UIContext` — the controller's description of the window |
| `ui/widgets.py` | shared sizing helpers and image conversion |

All three panes now live in one `QSplitter`, so the user can resize them.
`MainWindowUI` is still not a window; `TextScrapingReviewApp` remains the only
`QMainWindow`.

## Ownership boundary

`ui/` owns widget creation, layout, styling, menus, keyboard shortcuts, and all
widget state. `scraping_helper.py` owns application state, document loading,
MID navigation and mutation, scraping, audits, settings, and file output.

The controller no longer holds a single widget attribute. Where it used to do
`self.text_edit.setPlainText(...)` it now does `self.ui.set_content(...)`, and
where it read `self.notes.text()` it reads `self.ui.notes_text()`. A
guard in the refactor script checks that no widget name survives in the
controller.

### Reading state

`field_text` / `field_texts` / `notes_text` / `reviewer_notes_text` /
`toggles` / `is_toggled` / `counters` / `counter` / `metric_status` /
`metric_status_labels` / `scheme_name` / `restriction_choice` / `content` /
`selection` / `reserved_plain_keys` / `focus_widgets` / `warning_text` /
`active_panel_id` / `active_document_view`

### Presenting state

`set_field_text(s)` / `clear_fields` / `focus_field` / `set_notes_text` /
`set_reviewer_notes_text` / `set_toggle(s)` / `set_counter(s)` /
`set_counter_enabled` / `set_entry_position` / `set_info_values` /
`set_warning` / `set_hint` / `set_metric_status` /
`set_scheme` / `set_scheme_options` / `set_restriction_options` / `apply_mode` /
`set_status_message` / `set_content` / `clear_content` / `refresh_highlights` /
`show_page_pixmap` / `show_page_png` / `show_canvas_image` /
`refresh_document_view` / `show_panel`

## How the two halves talk

**Controller → UI.** `TextScrapingReviewApp.build_ui_context()` returns a
`UIContext` describing the fields, info labels, restriction options, and
classification schemes to build. That method is the only place MID vocabulary
is translated into UI terms — the `ui` package imports nothing from
`mid_schema` or pandas and can be built against any data model.

**UI → controller.** `MainWindowUI._connect_controller()` is the single place
that names controller methods. Sidebar buttons are declared as data in
`CONTROL_SPECS` and emit `actionTriggered(action_id)`; `ACTION_HANDLERS` maps
each id to a controller method. Adding a button is one line in each table.
State changes arrive as `addLevelRequested`, `schemeChanged`,
`toggleChanged(key, checked)`, `counterChanged(key, value)`, and
`fieldButtonClicked(key)`.

Mode visibility is declarative too: each `ControlSpec` lists the modes it
appears in, replacing the three hand-maintained widget lists on the app.

## Swappable right-hand panel

`ContentPanel` (in `ui/panels/base.py`) defines the contract: `set_content`,
`content`, `selection`, `highlight`, and a `transferRequested` signal. Panels
register themselves with `@register_panel` and are created by id, so the right
sidebar is no longer hard-wired to scraped text:

```python
from ui.panels import ContentPanel, register_panel

@register_panel
class MyPanel(ContentPanel):
    panel_id = "my_panel"
    display_name = "My Panel"
    ...
```

Two panels ship today — `scraped_text` (the previous behaviour, including
whitespace-tolerant highlighting) and `rendered_table` (HTML, replacing the
orphaned `table_viewer`). The **View** menu switches between them, and
`show_panel()` re-pushes the current payload so nothing is lost in the swap.

## Pulling content leftward

Every right-to-left transfer now goes through one path:

```
panel.request_transfer(key)  ->  transferRequested(key, text)
                             ->  MainWindowUI._on_transfer_requested
                             ->  app.on_content_transfer(key, text)
```

`on_content_transfer` runs classification-label extraction before writing the
snippet into the field, as the old `_fill_mid_field_from_selection` did.

Two ways to reach it:

- the existing shortcuts (`1`–`4`), and
- **new:** a right-click "Send Selection To ▸" menu in the panel, built from
  `LeftSidebar.transfer_targets()`, so it lists whatever fields the current
  schema defines rather than a fixed four.

To add a new pull gesture, emit `transferRequested` — no controller change.

## Behaviour changes

Deliberate fixes made along the way:

- **The image canvas is now in the layout.** It was created with the main
  window as its parent but never added to a layout, so `image_canvas.show()`
  opened a stray top-level window. It now shares a `QStackedWidget` with the
  page label in `DocumentView`.
- **`show_page` no longer indexes past the cache.** It read
  `page_text_cache[current_page_index]` into an unused local *before* the
  bounds check that was meant to protect it, so the `else` branch was
  unreachable and an out-of-range page raised `IndexError`.
- **Swallowed keys are derived, not hard-coded.** `eventFilter` used a literal
  list of digits `0`–`4`; it now consults `ui.reserved_plain_keys()`, which is
  built from the shortcuts actually bound. With fewer than four configured
  fields, the unbound digits reach the editor again.
- **`use_table_view` is gone.** Page caching asks the active panel for its
  content (`ui.content()`), which works for text and HTML panels alike, so the
  flag had no readers left.
- Panes are resizable; previously only the centre/right split was.

## Verification

- `python -m compileall` passes on all modules.
- Offscreen launch against the real `user_settings.json` (a five-column,
  non-legacy schema) builds all three panes, transfers a selection, swaps
  panels, and cycles all three modes.
- `pytest`: 189 passed, 4 failed, 1 xfailed. All 4 failures predate this work
  and are unrelated to it (two audit-runner report shapes, two MID-manager
  expectations).
- New `tests/test_ui_layer.py` covers the sidebar read/write API, mode
  visibility, the panel registry, highlighting, panel swapping, the transfer
  path, and the reserved-key filter. `application_factory` moved to
  `conftest.py` so both Qt test modules share it.

## Deliberately unchanged

- The MID hierarchy remains `stratobj → obj → goal → metric`; no `subgoal`.
- `MIDManager`, the scrapers, extractors, and audit runner are untouched.
- Restriction/audit logic still lives in the controller.

---

# Document-anchored MID rows

Previously a row was identified by its X/Y pair, which had three consequences:
the pair had to be filled in before the MID would load, the pair could not be
an editable field, and a blank pair made the row unreachable
(`load_mid_entry_document` returned `False` and navigation skipped past it).

The anchor is now **the column that names each row's document**.

## The rule

```
document column configured  ->  it is the anchor; X/Y are optional and may be editable
no document column          ->  X/Y compose the filename, so both are required
                                and neither may be editable (unchanged)
```

Only the anchor has to exist in the sheet. Every other configured column —
identifiers, editable fields, page, format, keyword — is created empty when
absent (`MIDSchema.creatable_columns`), logged as a warning, and written out on
export. A MID that is literally one column of filenames now works.

## What changed

| Where | Before | After |
| --- | --- | --- |
| `MIDSchema.validate_configuration` | X and Y always required; never editable | anchor required; X/Y optional and editable when a filename column exists |
| `MIDSchema.required_source_columns` | every configured column | the anchor only |
| `MIDManager.load_mid` | blank X/Y rejected | blank *anchor* rejected; missing columns created |
| `MIDManager.load_mid` | duplicate X/Y rejected | skipped while identifiers are editable; blanks never count as duplicates |
| `load_mid_entry_document` | `if not all(observation_key): return False` | fails only when the row names no document |
| page reset | keyed on the X/Y pair | keyed on `document_key`, so editing identifiers does not reset the page |
| `observation_label` / `observation_stem` | `x — y` / `x__y` | same when assigned; fall back to the document name when blank |
| info panel | always showed X and Y | omits an identifier that is an editable field or unconfigured |

New on `MIDSchema`: `identifier_columns`, `editable_identifiers`,
`configured_columns`, `creatable_columns()`, `document_name()`,
`document_stem()`, `document_key()`.

The **Configure MID Columns** dialog leads with the filename, marks X/Y
`<Not configured>`-able, and makes those two combos editable so a column the
sheet does not have yet can be typed in and created on load.

## Also fixed

Two crashes reachable once blank-identifier rows load: a scrape that failed
before setting `current_scrape_result` raised `AttributeError`, and the outer
handler that was supposed to report it referenced an undefined `filename`.
Both are now handled, and a failed scrape clears the panel instead of leaving
stale text.

## Contract change in the tests

`test_missing_required_column_is_rejected` asserted that a missing *editable*
column (`goal`) was fatal. That is the behaviour this change removes, so it is
replaced by `test_missing_anchor_column_is_rejected` plus
`test_missing_editable_column_is_created_not_rejected`.
`tests/test_document_anchor.py` covers the new contract end to end; the
`application_factory` fixture now takes `schema=` and `documents=`.

---

# Several observations from one document

One file can carry observations for several X/Y pairs. The data model already
allowed N rows to name the same file; what was missing was the workflow, the
efficiency, and an integrity story.

## Identity

An observation is `(document, X, Y)` — see `MIDSchema.uniqueness_columns`.
A pair may appear in many files and a file may host many pairs; only the same
pair twice in the same file is a collision.

Collisions are **reported, never fatal**. Identifiers are assigned inside the
app, so a MID saved mid-assignment has to be able to reopen. They surface in
three places:

- a warning line at load, listing example collisions;
- an amber banner in the left sidebar whenever the current row collides;
- an audit test, `duplicate_observation`, and a matching restriction so
  **Restrict to: duplicate_observation → Load Cases** walks them.

> **Occurrence seam.** If one document ever needs the same pair twice, add an
> occurrence column to the schema and append it to `uniqueness_columns`.
> Everything that checks for duplicates reads that one property. The column
> itself is deliberately not built yet.

## `DocumentSession`

`document_session.py` owns one open document and everything derived from it:
the `fitz` handle, the resolved page list, the scrape result, the page text
cache, table images, and overlays. Rows sharing a document *and* page range
share the session, so moving between observations in one file neither reopens
the PDF nor re-runs the scraper.

Scraped text is therefore **shared**: an edit made while recording one
observation is visible from the next, which is the intent — the text of page 5
is the text of page 5 whoever is looking at it.

The controller no longer holds `doc`, `page_indices`, `page_text_cache`,
`page_overlays`, or `current_scrape_result`; `page_indices`, `content_format`,
and `current_scrape_result` remain as read-only properties over the session.
`load_mid_entry_document` is now five short steps —
`_resolve_document_path`, `_open_document_session`, `_focus_page_from_row`,
`_present_scraped_content`, `show_page` — instead of one 120-line method.

Closing the previous session also fixes a leak: `fitz.open` was called once per
row and never closed.

## Add Observation from this Document

A sidebar control (`Ctrl+N`, user and dev modes) that splits the current row:
`MIDManager.clone_for_document` copies it, keeps the anchor, clears the
identifiers, editable fields, and review columns, sets `Page` to the page on
screen, marks `_gen`, inserts after the current row, and focuses the first
field. The open session is reused, so it is instant.

This is the flat-schema counterpart to the legacy `+` buttons, which still
serve the `stratobj → obj → goal → metric` hierarchy.

## Export naming

`observation_stem` is now document-first — `{document}__{X}__{Y}`, falling back
to `{document}` while unassigned — so two observations taken from one file no
longer overwrite each other in `data/accepted/`:

```
Combined_Report__DOJ__2024_full.txt
Combined_Report__HHS__2024_full.txt
Other_full.txt
```

Legacy MIDs move from `Agency__2024_full.txt` to
`AGENCY-2024__Agency__2024_full.txt`.

## Navigating within a document

- An **Observation: 2 of 3 in this document** line in the info block.
- A `same_document` restriction that filters the view to the current file.

Both live restrictions (`same_document`, `duplicate_observation`) are answered
from the MID itself, so they need no audit run and behave identically in dev
and reviewer mode. They are handled in `restrict_to_live_selection` before
`handle_load_failures` dispatches, which keeps them out of the two big
near-duplicate restriction methods.

## Also fixed

**A MID with no page-reference column was stuck on page 1.** `parse_pdf_pages`
returned `[0]`, so `next_page` refused to move and the rest of the document was
unreachable — which made a filename-only MID useless for any multi-page file.
An unconfigured page column now means *the whole document*: the session
resolves it once it knows the page count, and clamps out-of-range pages
(previously an out-of-range page raised from `load_page`).

---

# A configurable sidebar

Three more pieces of hard-coded domain knowledge left the sidebar: the
Target/Actual fields, the fixed checkbox set, and the fixed formulas a user
might want over the fields.

## Target and Actual are gone

They were two hard-coded fields in a sidebar whose other fields come from the
schema. They are no longer special: **configure `target` and `actual` as
editable columns if you want them back**, and they behave like any other field.

Their MID columns are untouched — the app simply no longer reads or writes
them, so existing values are preserved and still export. `no_t/a` still works
as a restriction over that older data.

Knock-on effects: `[` and `]` no longer transfer (and so become typable
again — `reserved_plain_keys` is derived from the bound shortcuts), the
right-click "Send Selection To" menu lists only real fields, and highlighting
covers only real fields.

## User-defined checkboxes

`settings["checkboxes"]` is a list; **Settings → Configure Checkboxes** edits
it. Only a MID column is required:

```json
{"column": "_verified", "label": "Verified", "shortcut": "Ctrl+V",
 "message": "Marked verified",
 "counter": {"column": "weeks_elapsed", "label": "Weeks:", "maximum": 52}}
```

`key` defaults to the column without its leading underscore, `label` to the
prettified column. A checkbox column the MID lacks is created on load, via
`MIDManager(boolean_columns=...)` — no spreadsheet work needed first.

`counter` generalises what was the Future-Dated/Years-to-eval pair: any
checkbox may own a number box that is live only while it is ticked and blanks
itself when unticked. `TOGGLE_COLUMNS` and `TOGGLE_MESSAGES` are gone; the
controller reads its definitions from settings.

The defaults reproduce the previous four checkboxes exactly, so an existing
`user_settings.json` behaves as before.

## Buttons that compute a field

`settings["fieldButtons"]`, edited in **Settings → Configure Field Buttons**.
Each names a target field and an expression over the editable fields:

```json
{"label": "10%", "target": "Match", "expression": "LMIG_Exp * 0.10",
 "decimals": 2}
```

The buttons render **beside the field they write into**, so `10%` and `30%`
sit next to Match, tooltipped with the formula.

A button may also carry `checkbox` (a checkbox key or MID column) and
`checkbox_action` (`check` / `uncheck` / `toggle`), which it applies after the
formula succeeds:

```json
{"label": "Sum", "target": "Total_Exp", "expression": "LMIG_Exp + Match",
 "checkbox": "_aggregate", "checkbox_action": "check"}
```

`MainWindowUI.set_toggle` grew a `notify` flag for this. Presenting a row still
blocks signals, but a button-driven change passes `notify=True` so the checkbox
behaves exactly as a click does — the companion counter follows it and
`toggleChanged` reaches the controller. A button naming a checkbox that is not
configured logs a warning and simply computes its field.

### The formula language

`field_formula.py` parses expressions with `ast` and walks them against an
allow-list — never `eval`. Everything outside it — attribute access,
subscripts, comparisons, comprehensions, any other call — is rejected with a
message naming what was wrong. `__import__("os").system(…)` fails at the
allow-list, not at runtime.

Fields arrive as text (`FieldText`, a `str` tagged with the name the formula
knows it by) and convert on demand, so one expression language covers both
jobs:

* **numbers** — `+ - * / // % **`, unary `+ -`, `abs / min / max / round`.
  Conversion goes through `to_number`, which handles what published documents
  actually contain: `$1,234,567.00`, `12%`, accounting negatives like `(500)`.
* **text** — `&` joins (`ast.BitAnd`), plus `TEXT_FUNCTIONS`: `concat`,
  `lower`, `upper`, `title`, `sentence`, `camel`, `pascal`, `snake`, `kebab`,
  `trim`, `replace`.

`evaluate` returns a float or a str; `format_result` rounds the former to the
button's `decimals` and passes the latter through untouched.

`+` stays arithmetic even between two strings. Overloading it would make a
formula's meaning depend on whether a scraped field happened to parse as a
number, so joining is always written `&` or `concat()`, and the error for
`"a" + "b"` says so. The case functions share one word-splitter, which breaks
on separators *and* on camel humps, so `LMIGExpTotal` and `lmig exp total`
reduce alike.

`FieldText` exists so a failed conversion can name its source: the tag is what
turns a bare "not a number" into *"'LMIG_Exp' is empty or is not a number"*.

Failures are reported, never destructive: pressing `10%` with an empty
`LMIG_Exp` leaves Match alone — and leaves any linked checkbox alone — and puts
the message in the status bar. The dialog validates as you type, so a broken
formula is caught where it is written.

## Tab and Shift+Tab

`configure_text_box` sets `setTabChangesFocus(True)`, so a multi-line editor
moves focus instead of swallowing Tab — including the right-hand panel, which
would otherwise dead-end the focus chain.

`LeftSidebar.apply_focus_chain()` then sets an explicit order over
`focus_widgets()`: fields → scheme → status radios → each checkbox followed by
its own counter → notes → reviewer notes. It is re-applied whenever the status
radios are rebuilt, since those widgets are destroyed and recreated when the
scheme changes.

## Layout

- Previous/Next Page and Previous/Next Entry are now paired on single rows
  (`< Page | Page >`, `< Entry | Entry >`), via `ControlSpec.group`:
  consecutive controls sharing a group id share a row.
- Text-field minimum height halved, 32px → 16px (`TEXT_BOX_MIN_HEIGHT`).

---

# Modules own their settings

Settings were a flat list of every knob in the program. Now a *module* — the
document viewer, each content panel — declares what it can be configured with,
and the settings window draws whatever it finds.

## Declaring

`module_settings.py` is deliberately Qt-free: it describes settings, it does
not draw them.

```python
@register_panel
@register_module_settings
class ScrapedTextPanel(ContentPanel):
    panel_id = "scraped_text"
    supports_number_key_transfer = True

    MODULE_SETTINGS = ModuleSettings(
        module_id="scraped_text",
        display_name="Scraped Text Panel",
        settings=(
            BoolSetting("numberKeyTransfer", "...", default=True),
            IntSetting("transferFieldCount", "...", default=4, minimum=1, maximum=9),
        ),
    )
```

`BoolSetting` / `IntSetting` / `ChoiceSetting` / `TextSetting` cover what the
dialog can render. Every spec coerces its stored value, so a hand-edited
settings file falls back to defaults instead of raising.

The number-key transfer that used to be hard-coded in `MainWindowUI` is now
the panel's: `_transfer_keys()` asks the active panel whether it supports the
gesture at all (`supports_number_key_transfer`, a code fact) and then whether
the user wants it (`numberKeyTransfer`, a settings fact). Switching panels
rebinds the shortcuts. **Turning it off gives the digits back for typing into
fields** — the tension noted at the end of the previous round.

## Storing

```json
"moduleSettings": {
  "document_view": {"clickRotation": true, "keepRotationBetweenPages": false},
  "scraped_text": {"numberKeyTransfer": true, "transferFieldCount": 4},
  "some_old_panel": {"settingFromLastYear": 3}
}
```

Entries are **never pruned**. A module the user configured before keeps its
values while it is not loaded, and even if the module is gone from the build —
the dialog shows those read-only rather than dropping them.
`remember_loaded_modules()` writes an entry the first time a module appears, so
the file accumulates what the user has actually used.

## Showing

`visible_modules()` decides what the settings window offers:

| Mode | Shows |
| --- | --- |
| user / reviewer | only the modules currently on screen |
| dev | every registered module, plus anything the settings file remembers |

**Settings → Module Settings** opens a tab per module. Modules that are not
loaded are marked as such. Changes apply immediately — no restart — via
`ui.apply_module_settings()`.

# Click to rotate the page

Left-click turns the page 90° clockwise, right-click 90° counter-clockwise,
wrapping through `0 / 90 / 180 / 270`. The centre pane's `PageLabel` emits
`rotateRequested`; `DocumentView` holds the angle and applies a `QTransform`
in `refresh()`, so a resize keeps the rotation.

Two settings, both the viewer's own:

- `clickRotation` (default on) — turning it off also straightens the page.
- `keepRotationBetweenPages` (default off) — on, a sideways document stays
  turned as you page through it.

# Restart

A **Restart** button at the top of the control panel (`Ctrl+R`), which
relaunches and reopens on the row you were on.

- Unsaved changes prompt **Save / Discard / Cancel**. Cancel does nothing;
  Save that is itself cancelled abandons the restart rather than losing work.
- The position travels as `--resume-index N` on the command line, so there is
  no stale state file. Repeated restarts replace the flag rather than
  accumulating it, and a frozen build relaunches itself instead of the
  interpreter.
- An out-of-range resume position is logged and ignored.

## Also fixed

**The MID always looked edited.** `set_value` compared raw values, but a MID
is read as text while the application writes native types back — committing
the sidebar wrote `int 1` over the string `"1"` for `Page`, so simply
navigating marked the MID dirty and the restart prompt would have fired every
single time. `MIDManager._is_edit` now compares normalised values.

**Tests wrote to the real `user_settings.json`.** The fixture patched
`load_settings` but not `save_settings`, so `remember_loaded_modules` wrote the
developer's settings file — it was overwritten with a pytest temp path during
this work and has been restored. The fixture now redirects saves to `tmp_path`,
deep-copies `default_settings` (a shallow copy shared the nested dicts between
tests), and stubs `QMessageBox.question` so no test can block on a modal.

# Which rows have been edited

Two flags, deliberately separate, because they answer different questions.

## `MIDManager.entry_is_dirty()` — in memory only

*Has the user changed anything about the row that is open?* Set by
`set_value` whenever a write is a real change, and cleared by the
`current_index` setter, so every move to another row starts clean. It is never
written to the MID.

It exists because `_commit_sidebar_fields` runs on **every** navigation. Before
this, walking past a row rewrote all of its fields — harmless while the values
matched, but it meant a row nobody touched could not be distinguished from one
that had been worked on, and app-supplied defaults (a `Page` number, the
default classification scheme) would be written into rows the user only glanced
at. Commit now stages its values, and writes nothing unless the row is dirty
**and** `pending_changes` finds a real difference.

What counts as touching a row: typing in a field, a checkbox, a counter, a
status radio, the scheme combo, a field button, content transferred from the
right-hand panel, and turning to a different page — the page is written into
the row, so choosing a different one is a change to it. Presenting a row is
not: `LeftSidebar` already blocked its widgets' signals in every `set_*`
method, and `load_mid_fields_from_row` additionally suppresses the reports
while it fills the sidebar in.

Two paths feed it. `LeftSidebar.userEdited` fires when a person operates a
widget, and the `MainWindowUI` setters that write row values report themselves,
because they block the signals they would otherwise raise.

Reviewer mode is unaffected: marking a row `SEEN` is the reviewer workflow's
own record of having visited it, not a user edit, so it still happens on every
visit and does not mark the row edited.

## `_edited` — a real MID column

*Has a change to this row ever been saved?* A workflow column defaulting to
`False`, parsed back from the sheet like the other underscore booleans, and
written out with the MID. Set when a commit actually writes, and reset on
rows created by `clone_for_document`, `clone_for_child`, and
`duplicate_prior_year` — a new row has not been edited by anyone.

- **File → Go to First Unedited Entry** (`Ctrl+U`) commits the current row,
  then jumps to `first_unedited_index()`. The status bar reports
  `unedited_count()` for the current view; a fully edited view says so instead
  of moving.
- **File → Entry → Mark as Edited** is a checkable action reflecting
  `is_entry_edited()` for whichever row is open, updated by
  `update_info_labels`. Setting it by hand goes through `set_entry_edited`,
  which writes the flag without going through `set_value` — the flag records
  that a row was edited, it is not itself one of the row's edits.

`File → Entry` exists to be filled: it is held on `MainWindowUI.entry_menu` so
further per-entry controls have somewhere to go.

# Entry labels are configurable

`MIDSchema.observation_label` composed `f"{x} — {y}"` and nothing else. It now
reads `entry_label`, a key into `ENTRY_LABEL_FORMATS`, set from **Configure MID
Columns → Entry label** and stored as `midSchema.entryLabel`:

`X — Y` (the default, unchanged), `X (Y)`, `X Y`, `XY`, `Y — X`, `Filename`,
`Filename (X — Y)`.

Every caller already went through `observation_label`, so the viewer, the
status bar, the logs, and the audit report all follow the setting. A blank
identifier is dropped rather than leaving a stray separator; a row with no
identifiers still falls back to its filename. An unknown key in a hand-edited
settings file falls back to the default rather than stopping the application
from starting.

## Also fixed

**Configure MID Columns forgot its editable columns.** The dialog built each
`QListWidgetItem` and called `setSelected` on it *before* `addItem`, and
selection does not take on an item the list does not own yet. Reopening the
dialog therefore showed nothing selected, and pressing OK failed validation
with "Select at least one MID column to interact with". Selection now follows
`addItem`. The schema-building half of `accept` was also split out as
`build_schema`, so the dialog can be tested without a dialog that was never
shown having to close itself.

## Suggested next step

`load_audit_failures` and `restrict_for_reviewer` are still near-identical
~110-line copies of each other. Both build a boolean mask over the MID and hand
the matching positions to `restrict_to_rows`; the only real difference is which
test names they accept. `restrict_to_live_selection` shows the shape the merged
version should take. That is the next cohesive behaviour to extract, into a
MID-restriction module.
