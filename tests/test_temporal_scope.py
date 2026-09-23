import pytest
from backend import evidence_scope
from tests.test_evidence_scope import span,verdict


def check(original,claim,condition_claim=None,conditions=True):
    e=dict(span(),quote=original,claim=claim)
    pairs=[dict(source_condition=original,claim_condition=condition_claim or claim,status='matched',reason='模型声称相同')] if conditions else []
    evidence_scope.apply([e],[verdict(conditions=pairs)])
    return e


@pytest.mark.parametrize('original,claim',[
    ('The response likely occurred approximately 6 seconds after the signal.','反应很可能发生在信号后约6秒内。'),
    ('The outcome persisted for at least 8 months.','结果持续8个月。'),
    ('The task ended within 2 minutes.','任务在2分钟这个时点结束。'),
    ('The event occurred between 3 and 5 days after treatment.','事件发生在治疗后5天。'),
])
def test_positive_scope_verdict_cannot_change_a_time_point_bound_or_window(original,claim):
    e=check(original,claim)
    assert e['support']=='unsupported' and e['support_checks']['scope']=='unknown'


def test_audit_cannot_omit_the_claims_time_condition():
    e=check('It likely occurred approximately 6 seconds after the signal.','很可能发生在信号后约6秒内。','很可能')
    assert e['support']=='unsupported' and '时间' in e['support_reason']


@pytest.mark.parametrize('original,claim',[
    ('The response likely occurred approximately 6 seconds after the signal.','反应很可能发生在信号后约6秒时。'),
    ('The outcome persisted for at least 8 months.','结果持续至少8个月。'),
    ('The task ended within 2 minutes.','任务在120秒内结束。'),
    ('The event occurred between 3 and 5 days after treatment.','事件发生在治疗后3至5天。'),
])
def test_matching_time_relation_and_exact_unit_conversion_remain_usable(original,claim):
    assert check(original,claim)['support']=='supported'


def test_number_and_percentage_without_a_duration_are_not_time_constraints():
    assert check('The study observed 63% in group 4.','第4组观察到63%。',conditions=False)['support']=='supported'


def test_a_counterpart_cannot_hide_the_upper_bound_in_its_full_claim():
    assert check('The event occurred at 6 seconds.','事件发生在6秒内。','6秒')['support']=='unsupported'


def test_bibliographic_calendar_dates_do_not_become_duration_requirements():
    assert check('Published on 8 May 2021.','发表于2021年5月8日。',conditions=False)['support']=='supported'


@pytest.mark.parametrize('original,claim',[
    ('A measurement within the past 6 months.','过去6个月内的测量。'),
    ('A measurement in the last 12 months.','最近12个月的测量。'),
    ('A change within the following 15 milliseconds.','接下来15毫秒内的变化。'),
])
def test_lookback_and_forward_windows_keep_their_meaning(original,claim):
    assert check(original,claim)['support']=='supported'


def test_temporal_rule_changes_invalidate_previous_analysis(monkeypatch,tmp_path):
    from backend import research
    rule=tmp_path/'synthetic_rule.py';rule.write_text('LIMIT = 1')
    monkeypatch.setattr(evidence_scope.temporal_scope,'__file__',str(rule))
    before=research.analysis_signature();rule.write_text('LIMIT = 2')
    assert research.analysis_signature()!=before
