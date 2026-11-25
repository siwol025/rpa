"""엑셀 템플릿 채우기 단위 테스트: 실제 템플릿(templates/report.xlsx)으로 확인한다."""

import io
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import openpyxl
import pytest

from app.services.excel_report import CellValue, TableData, fill_template

TEMPLATE = (Path(__file__).resolve().parents[2] / "templates" / "report.xlsx").read_bytes()
T0 = datetime(2026, 11, 23, 5, 30, 0, tzinfo=UTC)  # 14:30 KST


def _call_row(call_id: int = 1, **overrides: CellValue) -> list[CellValue]:
    values: dict[str, CellValue] = {
        "id": call_id,
        "call_datetime": T0,
        "agent": "김상담",
        "client": "가나상사",
        "category": "불만",
        "question": "환불 문의",
        "action": "환불 안내",
        "summary": "요약",
        "follow_up_required": "필요",
        "follow_up": "재연락",
        "status": "확인필요",
        **overrides,
    }
    return list(values.values())


def _fill(calls: list[list[CellValue]], errors: list[list[CellValue]] | None = None) -> bytes:
    return fill_template(
        TEMPLATE,
        [TableData("tblCalls", calls), TableData("tblErrors", errors or [])],
    )


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _text(data: bytes, name: str) -> str:
    return _parts(data)[name].decode("utf-8")


def test_rows_are_written_with_values_styles_and_formula_columns() -> None:
    data = _fill([_call_row(1), _call_row(2, follow_up_required=None, status="정상")])

    sheet = openpyxl.load_workbook(io.BytesIO(data))["통화이력"]
    assert [c.value for c in sheet[2]][:11] == [
        1,
        datetime(2026, 11, 23, 14, 30),
        "김상담",
        "가나상사",
        "불만",
        "환불 문의",
        "환불 안내",
        "요약",
        "필요",
        "재연락",
        "확인필요",
    ]
    assert sheet["I3"].value is None
    assert sheet["K3"].value == "정상"
    assert "yy" in sheet["B2"].number_format  # 열 스타일(날짜 서식)을 셀에 적용
    assert sheet["L3"].value.startswith("=IF(tblCalls[[#This Row],[통화일시]]")


def test_table_dimension_and_conditional_format_ranges_grow() -> None:
    data = _fill([_call_row(i) for i in range(1, 2502)])  # 2501행 → 마지막 행 2502

    table = _text(data, "xl/tables/table1.xml")
    sheet = _text(data, "xl/worksheets/sheet2.xml")
    assert 'ref="A1:N2502"' in table
    assert '<autoFilter ref="A1:N2502"' in table
    assert '<dimension ref="A1:N2502"/>' in sheet
    assert 'sqref="A2:K2502"' in sheet


def test_conditional_format_range_is_not_shrunk() -> None:
    sheet = _text(_fill([_call_row(1)]), "xl/worksheets/sheet2.xml")

    assert 'sqref="A2:K2000"' in sheet
    assert '<dimension ref="A1:N2"/>' in sheet


def test_error_rows_go_to_error_table() -> None:
    data = _fill([], [[7, "a.wav", "STT", "타임아웃", T0, 2]])

    sheet = openpyxl.load_workbook(io.BytesIO(data))["예외"]
    assert [c.value for c in sheet[2]] == [
        7,
        "a.wav",
        "STT",
        "타임아웃",
        datetime(2026, 11, 23, 14, 30),
        2,
    ]
    assert 'ref="A1:F2"' in _text(data, "xl/tables/table2.xml")


def test_strings_are_escaped_and_never_formulas() -> None:
    data = _fill([_call_row(1, question='=HYPERLINK("x")<b>&', action="줄\n바꿈\x01\x0b끝")])

    sheet = openpyxl.load_workbook(io.BytesIO(data))["통화이력"]
    assert sheet["F2"].value == '=HYPERLINK("x")<b>&'
    assert sheet["F2"].data_type == "s"
    assert sheet["G2"].value == "줄\n바꿈끝"


def test_empty_string_cell_is_omitted() -> None:
    sheet = _text(_fill([_call_row(1, client="")]), "xl/worksheets/sheet2.xml")

    assert 'r="D2"' not in sheet


def test_calc_chain_removed_and_full_calc_on_load() -> None:
    parts = _parts(_fill([_call_row(1)]))

    assert "xl/calcChain.xml" not in parts
    assert b"calcChain" not in parts["xl/_rels/workbook.xml.rels"]
    assert b"calcChain" not in parts["[Content_Types].xml"]
    assert re.search(rb'<calcPr [^>]*fullCalcOnLoad="1"', parts["xl/workbook.xml"])


def test_other_parts_are_byte_identical() -> None:
    before = _parts(TEMPLATE)
    after = _parts(_fill([_call_row(1)], [[7, "a.wav", None, None, None, 0]]))
    changed = {
        "xl/worksheets/sheet2.xml",
        "xl/worksheets/sheet3.xml",
        "xl/tables/table1.xml",
        "xl/tables/table2.xml",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "[Content_Types].xml",
        "xl/calcChain.xml",
    }

    assert {name: data for name, data in before.items() if name not in changed} == {
        name: data for name, data in after.items() if name not in changed
    }


def test_template_keeps_pivot_refresh_on_load() -> None:
    # 서버는 피벗을 계산하지 않는다. 열 때 새로 고침이 꺼진 양식이 들어오면 대시보드가 비게 된다.
    assert b'refreshOnLoad="1"' in _parts(TEMPLATE)["xl/pivotCache/pivotCacheDefinition1.xml"]


def test_no_rows_keeps_tables_unchanged() -> None:
    before = _parts(TEMPLATE)
    after = _parts(_fill([]))

    for name in ("xl/worksheets/sheet2.xml", "xl/tables/table1.xml", "xl/tables/table2.xml"):
        assert after[name] == before[name]


def test_wrong_column_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="tblCalls"):
        _fill([[1, 2]])


def test_unknown_table_is_rejected() -> None:
    with pytest.raises(ValueError, match="tblNope"):
        fill_template(TEMPLATE, [TableData("tblNope", [])])
