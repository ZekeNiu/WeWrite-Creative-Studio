import json
import pytest
from pydantic import BaseModel
from backend.structured_output import parse,restore_closing_delimiters


class Result(BaseModel):
    points:list[str]
    source_ids:list[str]


def test_missing_array_bracket_recovers_exact_strings_without_changing_ids():
    raw='{"points":"原文结论", "含\\"引号\\"的文字"],"source_ids":["Sabc"]}'
    assert parse(raw,Result)==dict(points=['原文结论','含"引号"的文字'],source_ids=['Sabc'])


def test_array_restoration_cannot_absorb_object_fields_or_truncated_output():
    for raw in ('{"points":"一句话","source_ids":["S1"]}', '{"points":"未完成',
                '{"points":"句子","source_ids":"S1"]}',
                json.dumps(dict(points=['A'],source_ids=['S1']))*2):
        with pytest.raises(ValueError):parse(raw,Result)


class NestedResult(BaseModel):
    report:Result
    sources:list[Result]


def test_wrong_closing_types_preserve_nested_content_and_escaped_strings():
    value=dict(report=dict(points=['原文 [ ] { } "引号" \\'],source_ids=['Sabc']),
               sources=[dict(points=['分母 5'],source_ids=['Sxyz'])])
    original=json.dumps(value,ensure_ascii=False)
    broken=original.replace('"Sabc"]}', '"Sabc"]]').replace('"Sxyz"]}]', '"Sxyz"]}}')
    assert restore_closing_delimiters(broken)==original
    assert parse('```json\n'+broken+'\n```',NestedResult)==value


def test_closing_repair_never_completes_truncation_or_accepts_multiple_results():
    complete='{"report":{"points":["P"],"source_ids":["S1"]],"sources":[]}'
    for raw in (complete[:-1],complete[:-3]+'"unfinished',complete*2,
                complete+'}', '{"report":{"points":["P"],"source_ids":["S1"]},"sources":[}'):
        with pytest.raises(ValueError):parse(raw,NestedResult)


def test_repair_keeps_content_errors_for_strict_validation():
    for raw in ('{"points":["P"],"source_ids":["S1" "S2"]]',
                '{"points":["P"],"source_ids":[42]]'):
        with pytest.raises(ValueError):parse(raw,Result)
