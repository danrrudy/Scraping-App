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


# ----------------------------------------------------------------------
# Text formulas
# ----------------------------------------------------------------------
@pytest.fixture
def text_values():
    return field_formula.field_values(
        {"Gov": "city of ann arbor", "FY": "2024", "Notes": "a,b,c", "Match": "1000"}
    )


def test_ampersand_joins_fields_and_literals(text_values):
    assert (
        field_formula.evaluate('Gov & " FY" & FY', text_values)
        == "city of ann arbor FY2024"
    )
    assert (
        field_formula.evaluate('concat(Gov, " FY", FY)', text_values)
        == "city of ann arbor FY2024"
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("upper(Gov)", "CITY OF ANN ARBOR"),
        ("lower('MiXeD')", "mixed"),
        ("title(Gov)", "City Of Ann Arbor"),
        ("sentence(Gov)", "City of ann arbor"),
        ("camel(Gov)", "cityOfAnnArbor"),
        ("pascal(Gov)", "CityOfAnnArbor"),
        ("snake(Gov)", "city_of_ann_arbor"),
        ("kebab(Gov)", "city-of-ann-arbor"),
        ("trim('  padded  ')", "padded"),
    ],
)
def test_case_changing_functions(text_values, expression, expected):
    assert field_formula.evaluate(expression, text_values) == expected


def test_case_changes_split_an_existing_camel_case_name():
    values = field_formula.field_values({"Gov": "LMIGExpTotal"})
    assert field_formula.evaluate("snake(Gov)", values) == "lmig_exp_total"
    assert field_formula.evaluate("kebab(Gov)", values) == "lmig-exp-total"


def test_replacement_swaps_every_occurrence(text_values):
    assert field_formula.evaluate('replace(Notes, ",", "-")', text_values) == "a-b-c"
    assert field_formula.evaluate('replace(Notes, ",", "")', text_values) == "abc"

    with pytest.raises(FormulaError, match="empty string"):
        field_formula.evaluate('replace(Notes, "", "-")', text_values)


def test_a_number_used_as_text_loses_its_trailing_zeros(text_values):
    assert field_formula.evaluate('"n=" & (Match * 2)', text_values) == "n=2000"
    assert field_formula.evaluate('"n=" & (Match / 8)', text_values) == "n=125"
    assert field_formula.evaluate('"n=" & (Match / 3)', text_values).startswith(
        "n=333.33"
    )


def test_text_results_ignore_the_decimal_setting():
    assert field_formula.format_result("Ann Arbor", 2) == "Ann Arbor"


def test_plus_stays_arithmetic_and_says_so(text_values):
    # Gov holds text, so "+" is a mistake; the message points at "&".
    with pytest.raises(FormulaError, match="empty or is not a number"):
        field_formula.evaluate("Gov + FY", text_values)
    with pytest.raises(FormulaError, match="Use & or concat"):
        field_formula.evaluate('"a" + "b"', text_values)

    # Two numeric fields still add rather than joining.
    assert field_formula.evaluate("FY + Match", text_values) == 3024.0


def test_text_and_number_formulas_both_validate_against_the_columns():
    field_formula.validate('snake(Gov & "-" & FY)', ["Gov", "FY"])
    field_formula.validate('replace(Notes, ",", "-")', ["Notes"])

    with pytest.raises(FormulaError, match="not one of the editable fields"):
        field_formula.validate("upper(Nope)", ["Gov"])


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


def test_a_button_can_name_the_checkbox_it_also_sets():
    definitions = normalize_field_buttons(
        [
            {
                "label": "Sum",
                "target": "Total_Exp",
                "expression": "LMIG_Exp + Match",
                "checkbox": "_aggregate",
                "checkbox_action": "toggle",
            }
        ]
    )
    assert definitions[0]["checkbox"] == "_aggregate"
    assert definitions[0]["checkbox_action"] == "toggle"
    assert definitions[0]["tooltip"] == (
        "Total_Exp = LMIG_Exp + Match, toggles _aggregate"
    )


def test_a_button_without_a_checkbox_keeps_its_plain_tooltip():
    definition = normalize_field_buttons(LMIG_BUTTONS)[0]
    assert definition["checkbox"] == ""
    assert definition["tooltip"] == "Match = LMIG_Exp * 0.10"


def test_an_unreadable_checkbox_action_falls_back_to_checking():
    definitions = normalize_field_buttons(
        [
            {
                "label": "Sum",
                "target": "Match",
                "expression": "1",
                "checkbox": "_flag",
                "checkbox_action": "burn it down",
            }
        ]
    )
    assert definitions[0]["checkbox_action"] == "check"


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


# ----------------------------------------------------------------------
# Buttons that also set a checkbox
# ----------------------------------------------------------------------
AGGREGATE_CHECKBOXES = [
    {"column": "_flag", "label": "Flag"},
    {
        "column": "_aggregate",
        "label": "Aggregate",
        "counter": {"column": "years_to_evaluation", "label": "Years:"},
    },
]


def linked_button(action="check", checkbox="_aggregate"):
    return [
        {
            "label": "Sum",
            "key": "sum",
            "target": "Total_Exp",
            "expression": "LMIG_Exp + Local_Exp",
            "decimals": 0,
            "checkbox": checkbox,
            "checkbox_action": action,
        }
    ]


@pytest.mark.qt
@pytest.mark.integration
def test_a_button_can_tick_a_checkbox_as_it_writes_its_field(lmig_app):
    window = lmig_app(buttons=linked_button(), checkboxes=AGGREGATE_CHECKBOXES)
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "500")

    window.ui.left.field_buttons["sum"].click()

    assert window.ui.field_text("Total_Exp") == "1500"
    assert window.ui.toggles()["aggregate"] is True
    # The checkbox owns its counter, so linking must wake the counter too.
    assert window.ui.left.counter_boxes["aggregate"].isEnabled() is True

    window._commit_sidebar_fields()
    row = window.mid_manager.master_df.iloc[0]
    assert row["Total_Exp"] == "1500"
    assert bool(row["_aggregate"]) is True


@pytest.mark.qt
@pytest.mark.integration
def test_a_linked_button_can_untick_or_flip_the_checkbox(lmig_app):
    window = lmig_app(
        buttons=linked_button("toggle"), checkboxes=AGGREGATE_CHECKBOXES
    )
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "500")

    window.ui.left.field_buttons["sum"].click()
    assert window.ui.toggles()["aggregate"] is True
    window.ui.left.field_buttons["sum"].click()
    assert window.ui.toggles()["aggregate"] is False

    window = lmig_app(
        buttons=linked_button("uncheck"), checkboxes=AGGREGATE_CHECKBOXES
    )
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "500")
    window.ui.set_toggle("aggregate", True)

    window.ui.left.field_buttons["sum"].click()
    assert window.ui.toggles()["aggregate"] is False


@pytest.mark.qt
@pytest.mark.integration
def test_a_failed_formula_leaves_the_linked_checkbox_alone(lmig_app):
    window = lmig_app(buttons=linked_button(), checkboxes=AGGREGATE_CHECKBOXES)
    # Local_Exp is still empty, so the formula cannot run.
    window.ui.set_field_text("LMIG_Exp", "1000")

    window.ui.left.field_buttons["sum"].click()

    assert window.ui.field_text("Total_Exp") == ""
    assert window.ui.toggles()["aggregate"] is False


@pytest.mark.qt
@pytest.mark.integration
def test_a_checkbox_may_be_named_by_its_key_instead_of_its_column(lmig_app):
    window = lmig_app(
        buttons=linked_button(checkbox="aggregate"),
        checkboxes=AGGREGATE_CHECKBOXES,
    )
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "500")

    window.ui.left.field_buttons["sum"].click()
    assert window.ui.toggles()["aggregate"] is True


@pytest.mark.qt
@pytest.mark.integration
def test_a_button_linked_to_a_missing_checkbox_still_computes(lmig_app):
    window = lmig_app(
        buttons=linked_button(checkbox="_not_configured"),
        checkboxes=AGGREGATE_CHECKBOXES,
    )
    window.ui.set_field_text("LMIG_Exp", "1000")
    window.ui.set_field_text("Local_Exp", "500")

    window.ui.left.field_buttons["sum"].click()

    assert window.ui.field_text("Total_Exp") == "1500"
    assert window.ui.toggles() == {"flag": False, "aggregate": False}


@pytest.mark.qt
@pytest.mark.integration
def test_a_text_button_writes_its_result_verbatim(lmig_app):
    window = lmig_app(
        buttons=[
            {
                "label": "Slug",
                "key": "slug",
                "target": "Match",
                "expression": 'snake(Local_Exp & " " & LMIG_Exp)',
                "decimals": 2,
            }
        ]
    )
    window.ui.set_field_text("LMIG_Exp", "2024")
    window.ui.set_field_text("Local_Exp", "City of Ann Arbor")

    window.ui.left.field_buttons["slug"].click()

    assert window.ui.field_text("Match") == "city_of_ann_arbor_2024"


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
