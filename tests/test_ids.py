"""ids.py - the native/aggregated split and the id date-decoder.

The digit count is the ONLY signal available at sitemap time, so getting it
wrong silently poisons every downstream cohort count.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from uplers_server import ids

from conftest import AGENTAI, AGGREGATED, ANOMALY, CONFIDO


# --- classification -------------------------------------------------------


def test_twelve_digit_id_is_native():
    assert ids.classify(CONFIDO) == "native"
    assert ids.digits(CONFIDO) == "100725001919"
    assert len(ids.digits(CONFIDO)) == ids.NATIVE_DIGITS == 12


def test_sixteen_digit_id_is_aggregated():
    assert ids.classify(AGGREGATED) == "aggregated"
    assert len(ids.digits(AGGREGATED)) == ids.AGGREGATED_DIGITS == 16


def test_thirteen_digit_anomaly_is_unknown_not_forced_into_a_bucket():
    # The live board holds exactly one of these; it must not be mislabelled.
    assert len(ids.digits(ANOMALY)) == 13
    assert ids.classify(ANOMALY) == "unknown"


@pytest.mark.parametrize("junk", ["HR", "XX123", "", "HR12AB34", "030826155648"])
def test_junk_classifies_unknown_and_is_invalid(junk):
    assert ids.classify(junk) == "unknown"
    assert ids.is_valid(junk) is False
    assert ids.digits(junk) is None


def test_lowercase_id_normalises_and_still_classifies_native():
    assert ids.normalise("  hr030826155648 ") == "HR030826155648"
    assert ids.classify("hr030826155648") == "native"
    assert ids.is_valid("hr030826155648") is True


# --- the date decoder -----------------------------------------------------


def test_decode_created_at_reads_ddmmyyhhmmss():
    assert ids.decode_created_at("HR030826155648") == datetime(2026, 8, 3, 15, 56, 48)


@pytest.mark.parametrize(
    "hr_number, why",
    [
        (AGGREGATED, "16-digit aggregated id carries no timestamp"),
        (ANOMALY, "13-digit anomaly is not a decodable native id"),
        ("not-an-id", "not an HR string at all"),
        ("HR010026120000", "month 00 is not a real month"),
        ("HR329126120000", "day 32 / month 91 are not a real date"),
    ],
)
def test_decode_created_at_returns_none_without_raising(hr_number, why):
    assert ids.decode_created_at(hr_number) is None, why


def test_created_at_iso_agrees_with_the_decoder():
    assert ids.created_at_iso(CONFIDO) == "2025-07-10T00:19:19"
    assert ids.created_at_iso(AGENTAI) == "2026-08-13T03:19:02"
    assert ids.decode_created_at(CONFIDO).isoformat() == ids.created_at_iso(CONFIDO)


@pytest.mark.parametrize("hr_number", [AGGREGATED, ANOMALY, "HR329126120000", "junk"])
def test_created_at_iso_is_none_wherever_the_decoder_is(hr_number):
    assert ids.decode_created_at(hr_number) is None
    assert ids.created_at_iso(hr_number) is None


# --- bulk extraction ------------------------------------------------------


def test_extract_from_text_dedupes_and_keeps_first_seen_order():
    blob = (
        "<urlset><url><loc>https://x/talent/HR030826155648</loc></url>"
        "<url><loc>https://x/talent/HR1173448373079993</loc></url>"
        "<url><loc>https://x/talent/HR030826155648</loc></url>"
        "<url><loc>https://x/about</loc></url>"
        "<url><loc>https://x/talent/HR010126120000</loc></url></urlset>"
    )
    assert ids.extract_from_text(blob) == [
        "HR030826155648",
        "HR1173448373079993",
        "HR010126120000",
    ]


def test_extract_from_text_finds_nothing_in_id_free_text():
    assert ids.extract_from_text("<urlset><url><loc>https://x/about</loc></url></urlset>") == []


def test_utcnow_iso_is_naive_second_resolution():
    value = ids.utcnow_iso()
    parsed = datetime.fromisoformat(value)
    assert len(value) == 19  # YYYY-MM-DDTHH:MM:SS, no microseconds, no offset
    assert parsed.tzinfo is None
    assert parsed.microsecond == 0
