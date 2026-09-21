from tools.quality_benchmark import found


def test_publisher_first_page_heading_counts_but_lecture_and_reference_do_not():
    case=dict(title='Synthetic System: A Distributed Database',urls=['conference.example/event/presentation/system'])
    paper=dict(title='final-42.pdf',url='https://conference.example/files/final-42.pdf',pages=[dict(text='Publisher header\nSynthetic System: A Distributed Database\nA. Author')])
    assert found(case,[paper])
    assert not found(case,[dict(paper,url='https://teaching.example/slides.pdf')])
    assert not found(case,[dict(paper,pages=[dict(text='Another article\n'+'Unrelated text. '*40+'References\n'+case['title'])])])


def test_author_pdf_heading_and_abstract_not_secondary_title_or_lecture():
    case=dict(title='Synthetic System: A Distributed Database')
    front=case['title']+'\nA. Author, B. Researcher\nResearch Laboratory\nABSTRACT\n'+'An original experiment with measurable results. '*40
    paper=dict(title='paper-07.pdf',url='https://author.example/paper.pdf',pages=[dict(text=front)],bibliography=None)
    assert found(case,[paper])
    assert not found(case,[dict(title=case['title']+' | A Reader Blog',url='https://reader.example/notes')])
    assert not found(case,[dict(title=case['title'],url='https://reader.example/notes',bibliography=dict(title=case['title']))])
    assert not found(case,[dict(paper,pages=[dict(text=case['title']+'\nPresenter: A. Student\nABSTRACT\n'+front)])])
    assert not found(case,[dict(paper,pages=[dict(text='A different paper\n'+'Introduction. '*100+'References\n'+front)])])
    assert not found(case,[dict(paper,pages=[dict(text='A Student\nExplaining the paper: '+front)])])


def test_expected_url_cannot_be_embedded_in_unrelated_host_or_path():
    case=dict(title='Original announcement',urls=['publisher.example/news/original'])
    assert found(case,[dict(url='https://www.publisher.example/news/original/?ref=home')])
    assert not found(case,[dict(url='https://reader.example/?url=publisher.example/news/original')])
    assert not found(case,[dict(url='https://publisher.example/news/original-commentary')])
