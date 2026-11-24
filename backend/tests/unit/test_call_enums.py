from enum import StrEnum

import pytest

from app.models.analysis import ACTION_STATUSES, CATEGORIES
from app.models.call_record import CALL_STATUSES, SOURCE_TYPES
from app.schemas.call import (
    CATEGORY_DB_VALUES,
    ActionStatus,
    CallStatus,
    Category,
    SourceType,
)


@pytest.mark.parametrize(
    ("enum", "db_values"),
    [
        (CallStatus, CALL_STATUSES),
        (SourceType, SOURCE_TYPES),
        (ActionStatus, ACTION_STATUSES),
    ],
)
def test_api_enum_matches_db_check_values(enum: type[StrEnum], db_values: tuple[str, ...]) -> None:
    assert [member.value for member in enum] == list(db_values)


def test_category_mapping_covers_codes_and_db_values() -> None:
    assert set(CATEGORY_DB_VALUES) == set(Category)
    assert sorted(CATEGORY_DB_VALUES.values()) == sorted(CATEGORIES)
