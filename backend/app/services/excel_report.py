"""엑셀 보고서 템플릿 채우기. xlsx 내부 XML을 직접 고친다(DB·HTTP 무관).

openpyxl로 열고 저장하면 템플릿의 차트·슬라이서가 사라진다. 그래서 표(`tblCalls` 등)가 있는
시트의 행과 표 범위만 바꾸고 나머지 파일은 바이트 그대로 둔다. 피벗 캐시는 템플릿에서
열 때 새로 고침(`refreshOnLoad`)이고, 수식은 열 때 다시 계산(`fullCalcOnLoad`)하도록 해서
Excel에서 열면 피벗·차트·슬라이서·대시보드가 채운 데이터로 다시 계산된다.
"""

import io
import posixpath
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape

from app.schemas.common import KST

CellValue = str | int | float | datetime | None

_EXCEL_EPOCH = datetime(1899, 12, 30)
# XML 1.0에 쓸 수 없는 제어 문자(탭·줄바꿈·CR 제외).
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_CALC_CHAIN = "xl/calcChain.xml"


@dataclass(frozen=True)
class TableData:
    """채울 표 이름과 행. 각 행은 수식(계산 열)을 뺀 열 순서대로의 값이다."""

    table: str
    rows: Sequence[Sequence[CellValue]]


def fill_template(template: bytes, tables: Sequence[TableData]) -> bytes:
    """템플릿 xlsx에 표 행을 채운 새 xlsx를 돌려준다. 행이 없는 표는 그대로 둔다."""
    with zipfile.ZipFile(io.BytesIO(template)) as source:
        parts = {info.filename: source.read(info) for info in source.infolist()}
        infos = source.infolist()

    for data in tables:
        table_path, sheet_path = _locate(parts, data.table)
        if data.rows:
            table_xml, sheet_xml = _fill_table(
                parts[table_path].decode("utf-8"), parts[sheet_path].decode("utf-8"), data
            )
            parts[table_path] = table_xml.encode("utf-8")
            parts[sheet_path] = sheet_xml.encode("utf-8")

    _drop_calc_chain(parts)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in infos:  # 원래 순서 유지([Content_Types].xml이 맨 앞)
            if info.filename in parts:
                target.writestr(info.filename, parts[info.filename])
    return output.getvalue()


def _locate(parts: dict[str, bytes], table_name: str) -> tuple[str, str]:
    """표 이름으로 표 XML과 그 표를 가진 시트 XML 경로를 찾는다."""
    for path, content in parts.items():
        is_table = path.startswith("xl/tables/") and path.endswith(".xml")
        if is_table and f' name="{table_name}"'.encode() in content:
            file_name = posixpath.basename(path)
            for rels_path, rels in parts.items():
                if rels_path.startswith("xl/worksheets/_rels/") and (
                    f'Target="../tables/{file_name}"'.encode() in rels
                ):
                    sheet = posixpath.basename(rels_path).removesuffix(".rels")
                    return path, f"xl/worksheets/{sheet}"
    raise ValueError(f"템플릿에 표가 없습니다: {table_name}")


def _fill_table(table_xml: str, sheet_xml: str, data: TableData) -> tuple[str, str]:
    columns = re.findall(r"<tableColumn [^>]*?(?:/>|>.*?</tableColumn>)", table_xml, re.S)
    formula_columns = {i for i, col in enumerate(columns) if "<calculatedColumnFormula" in col}
    value_count = len(columns) - len(formula_columns)
    first_col = _col_index(re.search(r' ref="([A-Z]+)1:', table_xml).group(1))  # type: ignore[union-attr]
    letters = [_col_letter(first_col + i) for i in range(len(columns))]
    styles = _column_styles(sheet_xml)
    formulas = _template_formulas(sheet_xml)

    rows_xml = []
    for offset, values in enumerate(data.rows):
        if len(values) != value_count:
            raise ValueError(f"{data.table} 행의 값 개수가 {value_count}개가 아닙니다")
        r = offset + 2
        cells: list[str] = []
        remaining = iter(values)
        for i, letter in enumerate(letters):
            style = styles.get(letter, "0")
            if i in formula_columns:
                formula = formulas.get(letter)
                if formula is not None:
                    cells.append(f'<c r="{letter}{r}"{_style(style)}><f>{formula}</f></c>')
            else:
                cells.append(_cell(f"{letter}{r}", style, next(remaining)))
        rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')

    last_row = len(data.rows) + 1
    last_ref = f"{letters[0]}1:{letters[-1]}{last_row}"
    header = re.search(r'<row r="1"[ >].*?</row>', sheet_xml, re.S)
    if header is None:
        raise ValueError(f"{data.table} 머리글 행이 없습니다")
    sheet_xml = re.sub(
        r"<sheetData>.*?</sheetData>|<sheetData/>",
        lambda _: f"<sheetData>{header.group(0)}{''.join(rows_xml)}</sheetData>",
        sheet_xml,
        count=1,
        flags=re.S,
    )
    sheet_xml = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="{last_ref}"/>', sheet_xml)
    sheet_xml = re.sub(
        r'sqref="([A-Z]+)2:([A-Z]+)(\d+)"',
        lambda m: f'sqref="{m.group(1)}2:{m.group(2)}{max(int(m.group(3)), last_row)}"',
        sheet_xml,
    )
    table_xml = re.sub(r'(<table [^>]*? ref=")[^"]*"', rf'\g<1>{last_ref}"', table_xml, count=1)
    table_xml = re.sub(r'(<autoFilter ref=")[^"]*"', rf'\g<1>{last_ref}"', table_xml, count=1)
    return table_xml, sheet_xml


def _column_styles(sheet_xml: str) -> dict[str, str]:
    """`<cols>`의 열 기본 스타일. 값을 쓴 셀에도 같은 스타일(날짜 서식 등)을 준다."""
    styles: dict[str, str] = {}
    for col in re.findall(r"<col [^>]*/>", sheet_xml):
        style = re.search(r' style="(\d+)"', col)
        if style:
            low = int(re.search(r' min="(\d+)"', col).group(1))  # type: ignore[union-attr]
            high = int(re.search(r' max="(\d+)"', col).group(1))  # type: ignore[union-attr]
            for index in range(low, high + 1):
                styles[_col_letter(index)] = style.group(1)
    return styles


def _template_formulas(sheet_xml: str) -> dict[str, str]:
    """템플릿 2행에 있는 계산 열 수식(이스케이프된 그대로)."""
    row = re.search(r'<row r="2"[ >].*?</row>', sheet_xml, re.S)
    if row is None:
        return {}
    return dict(re.findall(r'<c r="([A-Z]+)2"[^>]*><f>(.*?)</f>', row.group(0), re.S))


def _cell(ref: str, style: str, value: CellValue) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        local = value.astimezone(KST).replace(tzinfo=None) if value.tzinfo else value
        serial = (local - _EXCEL_EPOCH).total_seconds() / 86400
        return f'<c r="{ref}"{_style(style)}><v>{serial!r}</v></c>'
    if isinstance(value, bool):
        raise TypeError("bool 값은 표시 문자열로 바꿔서 넘긴다")
    if isinstance(value, int | float):
        return f'<c r="{ref}"{_style(style)}><v>{value!r}</v></c>'
    text = escape(_INVALID_XML_CHARS.sub("", value))
    # 인라인 문자열 셀은 '='로 시작해도 수식이 아니다.
    return (
        f'<c r="{ref}"{_style(style)} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
    )


def _style(style: str) -> str:
    return "" if style == "0" else f' s="{style}"'


def _drop_calc_chain(parts: dict[str, bytes]) -> None:
    """수식 셀 위치가 바뀌므로 계산 순서 파일을 지우고, 열 때 전체 재계산하게 한다."""
    parts.pop(_CALC_CHAIN, None)
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    parts["xl/_rels/workbook.xml.rels"] = re.sub(
        r'<Relationship [^>]*Target="calcChain.xml"[^>]*/>', "", rels
    ).encode("utf-8")
    types = parts["[Content_Types].xml"].decode("utf-8")
    parts["[Content_Types].xml"] = re.sub(
        r'<Override PartName="/xl/calcChain.xml"[^>]*/>', "", types
    ).encode("utf-8")
    workbook = parts["xl/workbook.xml"].decode("utf-8")
    if "fullCalcOnLoad=" not in workbook:
        workbook = workbook.replace("<calcPr ", '<calcPr fullCalcOnLoad="1" ', 1)
    parts["xl/workbook.xml"] = workbook.encode("utf-8")


def _col_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - ord("A") + 1
    return index


def _col_letter(index: int) -> str:
    letters = ""
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters
