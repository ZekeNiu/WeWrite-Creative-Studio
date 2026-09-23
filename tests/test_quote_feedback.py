from backend import materials,research


def test_unmatched_quote_feedback_shows_exact_read_text_without_repairing_it():
    sentence='The method improves retrieval only for the selected population.'
    original='Introduction. '+sentence[:27]+'\nTable 2: control results.\n'+sentence[27:]+' More findings.'
    source=materials.source('Two-column article',original)
    source['notebook']=dict(read_ranges=[dict(start=0,end=len(original))])
    hints=research.quote_feedback(sentence,source)
    assert hints and any('Table 2: control results.' in h['text'] for h in hints)
    assert all(h['text']==original[h['start']:h['end']] for h in hints)
    assert sentence not in original
    notes=dict(summary='',evidence=[dict(source_id=source['id'],quote=sentence,claim='Retrieval improves.',core_claim=True)],gaps=[],issues=[])
    checked=research.validate_spans(notes,[source])
    assert not checked['evidence'] and checked['issues'][0]['attempted_quote']==sentence


def test_quote_feedback_never_reads_hidden_or_unselected_material():
    hidden='This hidden paragraph exactly matches the requested evidence quotation.'
    source=materials.source('Long document','Already read material. '+hidden)
    source['notebook']=dict(read_ranges=[dict(start=0,end=22)])
    assert not research.quote_feedback(hidden,source)
    source['notebook']['read_ranges']=[dict(start=0,end=len(source['text']))]
    source['selected']=False
    assert not research.quote_feedback(hidden,source)


def test_quote_feedback_is_bounded_and_preserves_pdf_characters():
    text='Long preamble. '*150+'The ﬁrst effect may be present under condition C.'+' Other results. '*150
    source=materials.source('PDF',text);source['pages']=[dict(page=1,text=text)]
    source['notebook']=dict(read_ranges=[dict(start=0,end=len(text))])
    hints=research.quote_feedback('The first effect may be present under condition C.',source)
    assert 0<len(hints)<=3 and sum(len(h['text']) for h in hints)<=3000
    assert any('ﬁrst' in h['text'] for h in hints)
    assert all(h['text']==text[h['start']:h['end']] for h in hints)
