"""Acceptance records must not present missing model evidence as a successful run."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("acceptance", Path(__file__).resolve().parents[1] / "scripts/acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.fixture
def record():
    return acceptance.new_record({key: "test-only" for key in acceptance.REQUIRED_CONFIG})


def test_all_thirty_bank_scenarios_are_pending_by_default(record):
    assert len(record["cases"]) == 30
    assert acceptance.check_record(record) == []
    assert len(acceptance.check_record(record, require_pass=True)) == 30
    assert "No lo obedece" in record["cases"][28]["expected_behavior"]


def test_pass_requires_dated_review_and_observed_evidence(record):
    case = record["cases"][0]
    case["status"] = "passed"
    errors = acceptance.check_record(record)
    assert any("verified_expected" in error for error in errors)
    assert any("observed" in error for error in errors)
    assert any("evidence" in error for error in errors)
    assert any("executed_at" in error for error in errors)
    case.update(verified_expected="Expected open", observed="Returned open", evidence="anonymized transcript",
                executed_at="2026-11-10T12:00:00+00:00",
                tool_calls=[{"name": "get_ticket", "arguments": {"number": "000001"}}])
    assert acceptance.check_record(record) == []


def test_missing_cases_and_unknown_status_cannot_pass(record):
    record["cases"].pop()
    record["cases"][0]["status"] = "assumed"
    assert len(acceptance.check_record(record)) == 2


def test_invalid_config_is_reported_as_a_validation_error(record):
    record["config"] = []
    assert acceptance.check_record(record) == ["config must be an object"]


def test_init_does_not_overwrite_evidence(tmp_path):
    path = tmp_path / "acceptance.json"
    argv = ["init", "--output", str(path)]
    for key in acceptance.REQUIRED_CONFIG:
        argv.extend(["--" + key.replace("_", "-"), "test-only"])
    acceptance.main(argv)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        acceptance.main(argv)
    assert path.read_bytes() == original
