import asyncio
import copy
import json

import httpx
import pytest

from backend import evidence_state, materials, models, research, research_contract
from tests.test_structured_research import environment


def copied_source():
    source = materials.source('A document', 'The observation applies to group A.',
                              'https://publisher.example/document', 'web')
    source.update(original_url='https://index.example/record',
                  read_url='https://repository.example/copy', access_scope='fulltext',
                  identity_verified=True, identity_status='identified',
                  bibliography={'title': 'A document', 'publisher': 'Original publisher'},
                  metadata_provenance=[{'provider': 'index', 'url': 'https://index.example/record'}])
    return source


@pytest.mark.parametrize('schema', [models.EvidenceJudgements, models.EvidenceScopeAudit,
                                  models.CoverageAudit, models.AnswerScopeAudit])
def test_actual_audit_request_preserves_reader_provenance(monkeypatch, schema):
    sent = []

    def handler(request):
        sent.append(json.loads(json.loads(request.content)['messages'][-1]['content']))
        result = {'coverage': []} if schema is models.CoverageAudit else {'judgements': []}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(result)},
                                                    'finish_reason': 'stop'}]})

    _, article, job = environment(monkeypatch, handler)
    source = copied_source()
    article['sources'] = [source]
    contract = research_contract.ensure(article)
    before = copy.deepcopy(source)
    candidates = [dict(evidence_id='E1', source_id=source['id'])]
    if schema in (models.CoverageAudit, models.AnswerScopeAudit):
        question = contract['questions'][0]
        candidates = [dict(coverage=[dict(question_id=question['id'], question=question['text'],
                                         required=True, candidate_evidence_ids=[])])]
    asyncio.run(research.structured(article, 'sources', 'Synthetic audit', schema, job['id'], candidates))
    supplied = sent[0]['context']['sources'][0]
    for key in ('url', 'original_url', 'read_url', 'access_scope', 'identity_verified',
                'identity_status', 'metadata_provenance', 'bibliography'):
        assert supplied[key] == source[key]
    assert source == before


@pytest.mark.parametrize('field,value', [
    ('url', 'https://another.example/document'),
    ('read_url', 'https://another.example/copy'),
    ('original_url', 'https://another.example/record'),
    ('identity_verified', False),
    ('identity_status', 'unresolved'),
    ('access_scope', 'abstract'),
    ('metadata_provenance', [{'provider': 'other', 'url': 'https://other.example/record'}]),
])
def test_changed_reader_identity_cannot_reuse_prior_evidence_verdict(field, value):
    source = copied_source()

    def span_id():
        candidate = dict(source_id=source['id'], quote=source['text'], claim=source['text'])
        return research.validate_spans(dict(evidence=[candidate], gaps=[], issues=[]), [source])['evidence'][0]['evidence_id']

    old_key, old_span = evidence_state.source_key(source), span_id()
    assert span_id() == old_span
    source[field] = value
    assert evidence_state.source_key(source) != old_key
    assert span_id() != old_span
