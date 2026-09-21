import json
import pytest
from pydantic import BaseModel
from backend.structured_output import parse


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
