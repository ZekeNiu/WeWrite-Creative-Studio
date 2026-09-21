from tools.quality_benchmark import found


def test_publisher_first_page_heading_counts_but_lecture_and_reference_do_not():
    case=dict(title='Synthetic System: A Distributed Database',urls=['conference.example/event/presentation/system'])
    paper=dict(title='final-42.pdf',url='https://conference.example/files/final-42.pdf',pages=[dict(text='Publisher header\nSynthetic System: A Distributed Database\nA. Author')])
    assert found(case,[paper])
    assert not found(case,[dict(paper,url='https://teaching.example/slides.pdf')])
    assert not found(case,[dict(paper,pages=[dict(text='Another article\n'+'Unrelated text. '*40+'References\n'+case['title'])])])
