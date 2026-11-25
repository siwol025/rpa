from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.call import CallUpdateRequest
from app.schemas.common import KST
from app.services.call_metadata import is_metadata_incomplete


def _error(body: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationError) as exc_info:
        CallUpdateRequest.model_validate(body)
    (error,) = exc_info.value.errors()
    return dict(error)


def test_missing_key_null_and_value_are_distinguished() -> None:
    request = CallUpdateRequest.model_validate({"agent_name": None, "client_company": "가나상사"})

    assert request.model_fields_set == {"agent_name", "client_company"}
    assert request.metadata_changes() == {"agent_name": None, "client_company": "가나상사"}


def test_empty_body_has_no_changes() -> None:
    assert CallUpdateRequest.model_validate({}).metadata_changes() == {}


def test_editor_is_not_a_metadata_change() -> None:
    request = CallUpdateRequest.model_validate({"editor": " 김수정 "})

    assert request.editor == "김수정"
    assert request.metadata_changes() == {}


def test_strings_are_stripped() -> None:
    request = CallUpdateRequest.model_validate(
        {"agent_name": "  김상담 ", "client_company": " 가 "}
    )

    assert request.metadata_changes() == {"agent_name": "김상담", "client_company": "가"}


@pytest.mark.parametrize("field", ["agent_name", "client_company", "editor"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_string_is_rejected(field: str, value: str) -> None:
    error = _error({field: value})

    assert error["loc"] == (field,)
    assert error["type"] == "string_too_short"


@pytest.mark.parametrize(
    ("field", "limit"), [("agent_name", 50), ("client_company", 100), ("editor", 50)]
)
def test_max_length_counts_characters_after_strip(field: str, limit: int) -> None:
    CallUpdateRequest.model_validate({field: " " + "가" * limit + " "})

    assert _error({field: "가" * (limit + 1)})["type"] == "string_too_long"


@pytest.mark.parametrize("key", ["category", "question_summary", "review_completed", "status"])
def test_unknown_keys_are_rejected(key: str) -> None:
    error = _error({"agent_name": "김상담", key: "x"})

    assert error["loc"] == (key,)
    assert error["type"] == "extra_forbidden"


def test_call_datetime_without_offset_is_kst() -> None:
    request = CallUpdateRequest.model_validate({"call_datetime": "2026-11-23T14:30"})

    assert request.metadata_changes() == {
        "call_datetime": datetime(2026, 11, 23, 14, 30, tzinfo=KST)
    }


def test_call_datetime_with_offset_is_kept() -> None:
    request = CallUpdateRequest.model_validate({"call_datetime": "2026-11-23T05:30:00Z"})

    assert request.call_datetime == datetime(2026, 11, 23, 5, 30, tzinfo=UTC)


def test_call_datetime_null_clears() -> None:
    assert CallUpdateRequest.model_validate({"call_datetime": None}).metadata_changes() == {
        "call_datetime": None
    }


@pytest.mark.parametrize(
    "value", ["2000-01-01T00:00:00+09:00", "2100-12-31T23:59:59+09:00", "1999-12-31T15:00:00Z"]
)
def test_call_datetime_range_bounds_are_kst_dates(value: str) -> None:
    CallUpdateRequest.model_validate({"call_datetime": value})


@pytest.mark.parametrize(
    "value", ["1999-12-31T23:59:59+09:00", "2101-01-01T00:00:00+09:00", "2100-12-31T15:00:00Z"]
)
def test_call_datetime_out_of_range_is_rejected(value: str) -> None:
    error = _error({"call_datetime": value})

    assert error["loc"] == ("call_datetime",)
    assert error["type"] == "datetime_range"
    assert value not in error["msg"]


def test_call_datetime_empty_string_is_rejected() -> None:
    assert _error({"call_datetime": ""})["loc"] == ("call_datetime",)


# ---------------------------------------------------------------- metadata_incomplete 판정


@pytest.mark.parametrize(
    ("agent_name", "call_datetime", "expected"),
    [
        ("김상담", datetime(2026, 11, 23, tzinfo=KST), False),
        (None, datetime(2026, 11, 23, tzinfo=KST), True),
        ("김상담", None, True),
        (None, None, True),
    ],
)
def test_is_metadata_incomplete(
    agent_name: str | None, call_datetime: datetime | None, expected: bool
) -> None:
    assert is_metadata_incomplete(agent_name, call_datetime) is expected
