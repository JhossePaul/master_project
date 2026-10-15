"""Logs estructurados: forma JSON, límites y descarte de campos sensibles."""

import json
from datetime import UTC, datetime

from voc_common import FORBIDDEN_FIELDS, log_event
from voc_common.structured_log import MAX_STRING_LENGTH, build_event


def test_event_is_one_json_line_with_severity_and_message(capsys):
    record = log_event("INFO", "Batch finished", run_id="r1", messages=3)
    line = capsys.readouterr().out
    assert line.count("\n") == 1
    assert (
        json.loads(line)
        == record
        == {
            "severity": "INFO",
            "message": "Batch finished",
            "run_id": "r1",
            "messages": 3,
        }
    )


def test_sensitive_fields_are_dropped_and_reported():
    record = build_event(
        "WARNING",
        "Unexpected",
        run_id="r1",
        texto="Juan Pérez no puede entrar",
        usuario="Juan",
        next_token="opaque-cursor",  # noqa: S106 - valor de prueba
        raw_body=b"...",
    )
    assert record["run_id"] == "r1"
    assert record["dropped_fields"] == [
        "next_token",
        "raw_body",
        "texto",
        "usuario",
    ]
    dumped = json.dumps(record)
    assert "Juan" not in dumped and "opaque-cursor" not in dumped


def test_every_forbidden_field_is_removed():
    record = build_event("INFO", "x", **dict.fromkeys(FORBIDDEN_FIELDS, "v"))
    assert set(record) == {"severity", "message", "dropped_fields"}


def test_long_strings_are_truncated_recursively():
    long = "x" * (MAX_STRING_LENGTH + 50)
    record = build_event("INFO", "x", error=long, nested={"a": [long]})
    assert len(record["error"]) == MAX_STRING_LENGTH + 1
    assert record["error"].endswith("…")
    assert record["nested"]["a"][0] == record["error"]


def test_non_json_values_are_serialised_with_str(capsys):
    when = datetime(2026, 10, 15, tzinfo=UTC)
    log_event("INFO", "x", at=when, ids={"b", "a"} - {"b"})
    data = json.loads(capsys.readouterr().out)
    assert data["at"] == str(when) and data["ids"] == ["a"]
