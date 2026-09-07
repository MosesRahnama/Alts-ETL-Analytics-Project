from src.catalog.simple_pdf_extraction import page_grid as pg


def word(text, x0, x1, top=10.0):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 6}


def row(label, first, rest=("1", "2"), top=20.0):
    return {
        "top": top,
        "label": label,
        "cells": [first, *rest],
        "extents": [(90, 105), (190, 205), (290, 305)],
    }


def test_numeric_pattern_keeps_printed_units_and_rejects_punctuation():
    accepted = ("1.02x", "54.4 bps", "54.4 BPS", "(3.5%)", ",494,000")
    refused = (",", "text")
    assert all(pg.NUMERIC.fullmatch(value) for value in accepted)
    assert not any(pg.NUMERIC.fullmatch(value) for value in refused)


def test_detached_unit_joins_only_within_the_recorded_gap():
    close = pg._join_value_units([word("54.4", 10, 20), word("bps", 23, 30)])
    distant = pg._join_value_units([word("54.4", 10, 20), word("bps", 30, 37)])
    assert [item["text"] for item in close] == ["54.4 bps"]
    assert [item["text"] for item in distant] == ["54.4", "bps"]


def test_header_fragments_rejoin_and_stay_in_their_columns():
    centres = [(100.0, 4), (200.0, 4), (300.0, 4)]
    spans = [(95, 105), (195, 205), (295, 305)]
    line = {"words": [
        word("M", 94, 96), word("a", 96.1, 97), word("r", 97.1, 98),
        word("ke", 98.1, 100), word("t", 100.1, 101),
        word("In", 193, 196), word("ce", 196.1, 199), word("p", 199.1, 200),
        word("t", 200.1, 201), word("io", 201.1, 203), word("n", 203.1, 204),
        word("IR", 293, 296), word("R", 296.1, 297), word("(4)", 298, 302),
    ]}
    buckets, hits = pg._header_line(line, centres, spans, 80)
    labels = [" ".join(bucket) for bucket in buckets]
    assert labels == ["Market", "Inception", "IRR (4)"]
    assert hits == 3


def test_header_phrase_does_not_spread_across_neighbouring_columns():
    centres = [(100.0, 4), (200.0, 4), (300.0, 4)]
    spans = [(95, 105), (195, 225), (225, 305)]
    line = {"words": [word("Fair", 190, 205), word("Value", 207, 230)]}
    buckets, hits = pg._header_line(line, centres, spans, 80)
    assert buckets == [[], ["Fair Value"], []]
    assert hits == 1


def test_header_footnote_is_not_a_data_value():
    assert not pg._carries_data_values({"words": [word("(4)", 100, 108)]}, 80)
    assert pg._carries_data_values({"words": [word("$30", 100, 112)]}, 80)


def test_first_header_candidate_must_be_near_the_table():
    centres = [(100.0, 4), (200.0, 4)]
    block = [row("Fund", "1", rest=("2",), top=100)]
    block[0]["extents"] = [(90, 105), (190, 205)]
    distant = {"top": 50.0, "words": [word("Retirement", 90, 120, 50), word("Fund", 190, 210, 50)]}
    close = {"top": 65.0, "words": [word("Market", 90, 120, 65), word("Value", 190, 210, 65)]}
    blank, _ = pg._header_above(block, [distant], centres, 80)
    labels, _ = pg._header_above(block, [close], centres, 80)
    assert blank == ["", ""]
    assert labels == ["Market", "Value"]


def test_only_two_numeric_tokens_make_a_glued_one_row_cell():
    assert pg._glued_numeric_cell("30, 2022")
    assert not pg._glued_numeric_cell("54.4 bps")
    assert not pg._glued_numeric_cell("Total 2022")


def test_leading_year_folds_for_periods_but_not_fund_names():
    centres = [(100.0, 3), (200.0, 3), (300.0, 3)]
    periods = [row("Q1", "2008", top=20), row("Q2", "2008", top=30), row("Q3", "2008", top=40)]
    funds = [row("Alpha Fund", "2008", top=20), row("Beta Fund", "2009", top=30), row("Gamma Fund", "2010", top=40)]
    folded_centres, folded = pg._fold_leading_years(centres, periods)
    kept_centres, kept = pg._fold_leading_years(centres, funds)
    assert len(folded_centres) == 2
    assert [item["label"] for item in folded] == ["Q1 2008", "Q2 2008", "Q3 2008"]
    assert kept_centres == centres
    assert [item["label"] for item in kept] == ["Alpha Fund", "Beta Fund", "Gamma Fund"]


def test_value_band_retains_a_populated_nearby_leading_column():
    clusters = [(203, 12), (244, 2), (261, 26), (301, 29), (332, 26),
                (362, 20), (394, 23), (426, 45), (487, 15), (519, 13)]
    band = pg._value_band(clusters)
    assert [item[0] for item in band][:2] == [203, 261]


def test_value_band_drops_a_distant_vintage_before_fund_names():
    clusters = [(48, 53), (280, 53), (337, 54), (398, 53), (450, 53)]
    band = pg._value_band(clusters)
    assert [item[0] for item in band] == [280, 337, 398, 450]


def test_header_inheritance_requires_adjacency_and_uses_last_table():
    previous = {
        "page": 1,
        "columns": [100, 200],
        "headers": ["old-a", "old-b"],
        "rows": [
            {"headers": ["old-a", "old-b"]},
            {"headers": ["current-a", "current-b"]},
        ],
    }
    adjacent = {"page": 2, "columns": [100, 200], "headers": ["", ""], "rows": [{"headers": ["", ""]}]}
    skipped = {"page": 3, "columns": [100, 200], "headers": ["", ""], "rows": [{"headers": ["", ""]}]}
    pg.inherit_headers(adjacent, previous)
    pg.inherit_headers(skipped, previous)
    assert adjacent["headers"] == ["current-a", "current-b"]
    assert skipped["headers"] == ["", ""]


def test_page_summary_uses_the_most_complete_header_set():
    rows = [
        {"headers": ["Title", ""]},
        {"headers": ["Market Value", "IRR"]},
    ]
    assert pg._representative_headers(rows) == ["Market Value", "IRR"]
