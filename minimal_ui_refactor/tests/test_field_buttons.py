"""User-defined buttons that compute one editable field from the others."""

import pytest

import field_formula
from app_settings import normalize_checkboxes, normalize_field_buttons
from field_formula import FormulaError


LMIG_SCHEMA = {
    "xColumn": "FY",
    "yColumn": "Gov",
    "interactionColumns": ["LMIG_Exp", "Match", "Local_Exp", "Total_Exp"],
    "documentColumn": "source_file",
    "pageColumn": "",
    "formatColumn": "",
    "keywordColumn": "",
}

LMIG_BUTTONS = [
    {"label": "10%", "target": "Match", "expression": "LMIG_Exp * 0.10"},
    {"label": "30%", "target": "Match", "expression": "LMIG_Exp * 0.30"},
    {
        "label": "Sum",
        "target": "Total_Exp",
        "expression": "LMIG_Exp + Match + Local_Exp",
        "decimals": 0,
    },
]


# ----------------------------------------------------------------------
# Reading numbers out of scraped text
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234", 1234.0),
        ("1,234,567.89", 1234567.89),
        ("$1,234", 1234.0),
        ("  42 ", 42.0),
        ("-17.5", -17.5),
        ("(500)", -500.0),          # accounting-style negative
        ("($1,200)", -1200.0),
        ("12%", 12.0),
        ("", None),
        ("   ", None),
        ("n/a", None),
        (None, None),
    ],
)
def test_numbers_are_read_out_of_document_formatting(text, expected):
    assert field_formula.to_number(text) == expected


def test_column_names_become_usable_identifiers():
    assert field_formula.variable_name("LMIG Exp") == "LMIG_Exp"
    assert field_formula.variable_name("Table Name/Word Search") == "Table_Name_Word_Search"
    assert field_formula.variable_name("2024 total") == "n_2024_total"
    assert field_formula.variable_name("  ") == ""


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
@pytest.fixture
def values():
    return field_formula.field_values(
        {"LMIG_Exp": "$1,234,567.00", "Match": "1000", "Local_Exp": "(500)"}
    )


def test_the_worked_example_computes_a_percentage(values):
    result = field_formula.evaluate("LMIG_Exp * 0.10", values)
    assert field_formula.format_result(result) == "123456.70"

    result = field_formula.evaluate("LMIG_Exp * 0.30", values)
    assert field_formula.format_result(result) == "370370.10"


def test_arithmetic_and_allowed_functions_work(values):
    assert field_formula.evaluate("LMIG_Exp + Match + Local_Exp", values) == 1235067.0
    assert field_formula.evaluate("(Match + 500) / 2", values) == 750.0
    assert field_formula.evaluate("abs(Local_Exp)", values) == 500.0
    assert field_formula.evaluate("max(Match, 42)", values) == 1000.0
    assert field_formula.evaluate("round(LMIG_Exp / 3, 1)", values) == 411522.3
    assert field_formula.evaluate("2 ** 10", values) == 1024.0


def test_results_are_rounded_to_the_requested_precision():
    assert field_formula.format_result(123456.789, 2) == "123456.79"
    assert field_formula.format_result(123456.789, 0) == "123457"
    assert field_formula.format_result(-0.5, 1) == "-0.5"


@pytest.mark.parametrize(
    ("expression", "fragment"),
    [
        ('__import__("os").system("echo hi")', "functions"),
        ("open('x')", "functions"),
        ("Match.__class__", "not allowed"),
        ("[1, 2, 3]", "not allowed"),
        ("Match if Match else 0", "not allowed"),
        ("Match > 3", "not allowed"),
        ("lambda: 1", "not allowed"),
        ("'text' + 'more'", "Only numbers"),
        ("Unknown * 2", "not one of the editable fields"),
        ("Match / 0", "divides by zero"),
        ("", "empty"),
        ("1 +", "Could not read"),
    ],
)
def test_only_arithmetic_over_the_fields_is_permitted(values, expression, fragment):
    with pytest.raises(FormulaError, match=fragment):
        field_formula.evaluate(expression, values)


def test_an_empty_field_is_reported_rather_than_treated_as_zero():
    values = field_formula.field_values({"LMIG_Exp": "", "Match": "5"})
    with pytest.raises(FormulaError, match="empty or is not a number"):
        field_formula.evaluate("LMIG_Exp * 0.10", values)


def test_validation_catches_a_bad_formula_without_any_values():
    field_formula.validate("LMIG_Exp * 0.10", ["LMIG_Exp", "Match"])

    with pytest.raises(FormulaError, match="not one of the editable fields"):
        field_formula.validate("Nope * 2", ["LMIG_Exp"])


# ----------------------------------------------------------------------
# Settings normalization
# ----------------------------------------------------------------------
def test_button_definitions_fill_in_their_own_keys_and_tooltips():
    definitions = normalize_field_buttons(LMIG_BUTTONS)

    assert [item["key"] for item in definitions] == ["10", "30", "sum"]
    assert definitions[0]["tooltip"] == "Match = LMIG_Exp * 0.10"
    assert definitions[0]["decimals"] == 2
    assert definitions[2]["decimals"] == 0


def test_incomplete_button_definitions_are_dropped_not_fatal():
    definitions = normalize_field_buttons(
        [
            {"label": "ok", "target": "Match", "expression": "1"},
            {"label": "no target", "expression": "1"},
            {"target": "Match", "expression": "1"},
            {"label": "no formula", "target": "Match"},
            "not a mapping",
        ]
    )
    assert [item["label"] for item in definitions] == ["ok"]


def test_repeated_button_labels_still_get_distinct_keys():
    definitions = normalize_field_buttons(
        [
            {"label": "10%", "target": "Match", "expression": "1"},
            {"label": "10%", "target": "Total_Exp", "expression": "2"},
        ]
    )
    assert [item["key"] for item in definitions] == ["10", "10_2"]


def test_checkbox_definitions_fill_in_their_own_keys_and_labels():
    definitions = normalize_checkboxes(
        [{"column": "_needs_review"}, {"column": "_flag", "label": "Flag"}]
    )
    assert [item["key"] for item in definitions] == ["needs_review", "flag"]
    assert definitions[0]["label"] == "Needs Review"


def test_duplicate_checkbox_columns_are_collapsed():
    definitions = normalize_checkboxes(
        [{"column": "_flag"}, {"column": "_flag", "label": "Again"}]
    )
    assert len(definitions) == 1


# ----------------------------------------------------------------------
# In the application
# ----------------------------------------------------------------------
pytest.importorskip("PyQt5", reason="PyQt5 is required for application tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")


@pytest.fixture
def lmig_app(application_factory):
    rows = [
        {
            "source_file": "LMIG_A.pdf",
            "FY": "",
            "Gov": "",
            "LMIG_Exp": "",
            "Match": "",
            "Local_Exp": "",
            "Total_Exp": "",
        }
    ]

    def build(buttons=None, checkboxes=None):
        return application_factory(
            rows=rows,
            schema=LMIG_SCHEMA,
            documents={"LMIG_A.pdf"},
            extra_settings={
                "fieldButtons": LMIG_BUTTONS if buttons is None else buttons,
                **({} if checkboxes is None else {"checkboxes": checkboxes}),
            },
        )

    return build


@pytest.mark.qt
@pytest.mark.integration
def test_a_button_fills_its_target_field_from_the_others(lmig_app):
    window = lmig_app()
    window.ui.set_field_text("LMIG_Exp", "$1,234,567.00")

    window.ui.left.field_buttons["10"].click()
    assert window.ui.field_text("Match") == "123456.70"

    window.ui.left.field_buttons["30"].click()
    assert window.ui.field_text("Match") == "370370.10"


@pytest.mark.qt
@pytest.mark.integration
def test_a_button_can_read_a_field_another_button_just_wrote(lmig_app):
    window = lmig_app()
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "(500)")

    window.ui.left.field_buttons["10"].click()
    window.ui.left.field_buttons["sum"].click()
    # 1000 + 100 - 500, to zero decimals
    assert window.ui.field_text("Total_Exp") == "600"


@pytest.mark.qt
@pytest.mark.integration
def test_a_button_reports_a_missing_input_instead_of_writing(lmig_app):
    window = lmig_app()
    window.ui.set_field_text("Match", "untouched")

    window.ui.left.field_buttons["10"].click()

    assert window.ui.field_text("Match") == "untouched"
    assert "empty or is not a number" in window.statusBar().currentMessage()


@pytest.mark.qt
@pytest.mark.integration
def test_a_computed_value_is_committed_like_any_other_field(lmig_app):
    window = lmig_app()
    window.ui.set_field_text("LMIG_Exp", "2000")
    window.ui.left.field_buttons["10"].click()
    window._commit_sidebar_fields()

    assert window.mid_manager.master_df.iloc[0]["Match"] == "200.00"


@pytest.mark.qt
def test_a_button_targeting_an_unknown_field_is_skipped(lmig_app):
    window = lmig_app(
        buttons=[{"label": "Bad", "target": "not_a_field", "expression": "1"}]
    )
    assert window.ui.left.field_buttons == {}


@pytest.mark.qt
@pytest.mark.integration
def test_the_checkbox_set_comes_from_settings(lmig_app):
    window = lmig_app(
        checkboxes=[
            {"column": "_flag", "label": "Flag"},
            {"column": "_verified", "label": "Verified"},
        ]
    )
    left = window.ui.left

    assert list(left.toggle_boxes) == ["flag", "verified"]
    assert left.counter_boxes == {}

    window.ui.set_toggle("verified", True)
    window._commit_sidebar_fields()
    # The column did not exist in the sheet; it was created on load.
    assert bool(window.mid_manager.master_df.iloc[0]["_verified"]) is True
