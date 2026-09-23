from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator,field_validator

STAGES = ['topic', 'sources', 'outline', 'write', 'review', 'visual', 'layout']
LABELS = dict(zip(STAGES, ['选题', '素材', '大纲', '写作', '审核修改', '配图', '排版导出']))
LABELS['research']='检索规划与资料整理'
LABELS.update(revise='修改选段', image='图片', layout_advice='阅读与结构建议', search='搜索工具')
ROUTES = [*STAGES[:-1], 'revise', 'image', 'layout_advice', 'research']


class Brief(BaseModel):
    column: str = '运动科学'
    domain: str = ''
    topic: str = ''
    audience: str = '大众科普'
    words: int = Field(1800, ge=200, le=15000)
    persona: str = 'industry-observer'
    tone: str = '准确、深入、自然；减少套话和过度分点'
    purpose: str = ''
    include: str = ''
    avoid: str = '空泛开头、夸张标题、编造经历'
    recent_days: int = Field(90, ge=1, le=3650)


class Layout(BaseModel):
    theme: str = 'editorial-science'
    font_size: int = Field(16, ge=12, le=24)
    line_height: float = Field(1.8, ge=1.2, le=3)
    paragraph_gap: int = Field(18, ge=4, le=40)
    author: str = ''


class VisualSettings(BaseModel):
    enabled: bool = False
    count: int = Field(2, ge=1, le=6)
    size: Literal['1536x1024', '1024x1024', '1024x1536'] = '1536x1024'


class Topic(BaseModel):
    id: str = ''
    title: str
    angle: str
    audience: str = ''
    reason: str
    source_ids: list[str] = []
    reader_question: str = ''
    novelty: str = ''
    takeaway: str = ''
    questions: list[str] = Field(default_factory=list, max_length=8)
    key_claims: list[str] = Field(default_factory=list, max_length=8)
    evidence_status: str = '待调查'


class TopicsResult(BaseModel):
    topics: list[Topic] = Field(min_length=1, max_length=20)


class Claim(BaseModel):
    id: str
    text: str
    type: Literal['fact', 'inference', 'opinion', 'user_experience']
    source_ids: list[str] = []
    status: Literal['supported', 'bounded', 'unsupported']
    boundary: str = ''
    evidence: list[dict] = []


class EvidenceResult(BaseModel):
    summary: str
    claims: list[Claim]
    gaps: list[str] = []
    intent: Topic | None = None
    direction_change: str = ''


class Section(BaseModel):
    id: str
    title: str
    purpose: str
    points: list[str] = []
    claim_ids: list[str] = []


class OutlineResult(BaseModel):
    thesis: str
    reader_question: str
    takeaway: str
    counterpoint: str = ''
    boundary: str = ''
    sections: list[Section] = Field(min_length=1)


class Issue(BaseModel):
    id: str
    severity: Literal['blocker', 'major', 'minor']
    quote: str
    reason: str
    suggestion: str = ''
    source_ids: list[str] = []
    status: Literal['pending', 'accepted', 'rejected'] = 'pending'


class ReviewResult(BaseModel):
    decision: Literal['pass', 'revise', 'needs_input']
    summary: str
    issues: list[Issue]
    dimensions: dict[str, int] = {}
    title: str = ''
    alt_titles: list[str] = []
    digest: str = ''
    tags: list[str] = []


class ImagePlan(BaseModel):
    id: str
    role: Literal['cover', 'article']
    prompt: str
    caption: str = ''
    after_heading: str = ''


class VisualResult(BaseModel):
    images: list[ImagePlan]


class RevisionResult(BaseModel):
    replacement: str
    explanation: str


class Service(BaseModel):
    id: str
    name: str = 'APIKEY.FAN'
    base_url: str = 'https://api.apikey.fan'
    protocol: Literal['chat', 'responses', 'anthropic'] = 'chat'
    model: str = ''
    key: str | None = None
    key_set: bool = False
    input_price: float | None = Field(None, ge=0)
    output_price: float | None = Field(None, ge=0)
    image_price: float | None = Field(None, ge=0)
    currency: str = 'CNY'
    max_tokens: int = Field(8000, ge=256, le=64000)
    temperature: float | None = Field(None, ge=0, le=2)
    status: str = 'untested'
    image_status: str = 'untested'
    search_price: float | None = Field(None, ge=0)


class Route(BaseModel):
    service_id: str = ''
    model: str = ''


class SearchConfig(BaseModel):
    preference: Literal['native'] = 'native'
    allow_fallback: bool = True
    base_url: str = 'https://api.tavily.com'
    key: str | None = None
    key_set: bool = False
    enabled: bool = True
    native_service_id: str = ''
    native_model: str = ''
    native_protocol: Literal['inherit', 'responses', 'anthropic', 'gemini'] = 'inherit'
    academic_enabled: bool = True
    arxiv_enabled: bool = True
    openalex_key: str | None = None
    openalex_key_set: bool = False
    browser_enabled: bool = True
    page_render_enabled: bool = True
    pubmed_enabled: bool = True
    tavily_enabled: bool = False
    tavily_price: float | None = Field(None, ge=0)
    max_calls: int = Field(8, ge=1, le=100)
    max_pages: int = Field(16, ge=1, le=500)
    max_rounds: int = Field(2, ge=0, le=20)

    @model_validator(mode='before')
    @classmethod
    def migrate_strategy(cls,value):
        if isinstance(value,dict):
            value=dict(value,preference='native')
            value.setdefault('page_render_enabled',value.get('browser_enabled',True))
        return value


class ResearchQuery(BaseModel):
    query: str
    question: str = ''
    purpose: Literal['known_source','explore','counterevidence','updates'] = 'explore'
    source_type: Literal['academic','official','general','auto'] = 'auto'
    time_scope: Literal['all','recent'] = 'all'
    channel_queries: dict[str,str] = Field(default_factory=dict,max_length=8)


class RequiredEvidence(BaseModel):
    request_quote: str
    question: str


class ResearchPlan(BaseModel):
    needed: bool
    academic: bool = True
    queries: list[str | ResearchQuery] = Field(default_factory=list, max_length=8)
    questions: list[str] = Field(default_factory=list, max_length=12)
    reason: str = ''
    required_evidence: list[RequiredEvidence] = Field(default_factory=list,max_length=10)


class EvidenceSpan(BaseModel):
    question_ids: list[str] = Field(default_factory=list,max_length=12)
    claim_id: str = ''
    type: Literal['fact', 'inference', 'opinion', 'user_experience'] = 'fact'
    source_id: str
    quote: str
    claim: str
    boundary: str = ''
    source_type: str = ''
    adoption_reason: str = ''
    use_scope: str = ''
    quality: Literal['suitable', 'limited', 'insufficient', 'unassessed'] = 'unassessed'
    core_claim: bool = False


class ResearchIssue(BaseModel):
    id: str = ''
    text: str
    kind: Literal['blocking','limitation'] = 'blocking'
    source_ids: list[str] = Field(default_factory=list)
    claim: str = ''
    claim_id: str = ''
    status: Literal['open','resolved'] = 'open'
    resolution: str = ''
    priority: Literal['high','normal'] | None = None
    merged_ids: list[str] = Field(default_factory=list,max_length=24)


class ResearchNotes(BaseModel):
    summary: str
    evidence: list[EvidenceSpan] = Field(max_length=40)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    conflicts: list[str] = Field(default_factory=list, max_length=8)
    followup_queries: list[str] = Field(default_factory=list, max_length=4)
    issues: list[ResearchIssue] = Field(default_factory=list, max_length=24)
    intent: Topic | None = None
    direction_change: str = ''
    coverage: list['QuestionCoverage'] = Field(default_factory=list,max_length=32)
    source_notes: list['SourceNote'] = Field(default_factory=list,max_length=64)
    read_requests: list['SectionRead'] = Field(default_factory=list,max_length=4)


class EvidenceAdditions(BaseModel):
    evidence: list[EvidenceSpan] = Field(max_length=12)


class SourceNote(BaseModel):
    source_id: str
    category: Literal['design','results','counterevidence','limitations','scope']
    note: str
    quote: str


class SectionRead(BaseModel):
    source_id: str
    section_id: str
    reason: str


class QuestionCoverage(BaseModel):
    question_id: str
    status: Literal['supported','limited','contradicted','unresolved']
    reason: str


class CoverageVerdict(QuestionCoverage):
    evidence_ids: list[str] = Field(default_factory=list,max_length=40)
    requires_source_content: bool = True


class CoverageAudit(BaseModel):
    coverage: list[CoverageVerdict] = Field(max_length=32)


class EvidenceJudgement(BaseModel):
    evidence_id: str
    support: Literal['supported','limited','contradicted','unsupported']
    reason: str
    basis: Literal['observed','author_interpretation','external_reference','not_applicable','unassessed'] = 'unassessed'
    source_origin: Literal['primary','secondary','background','unassessed'] = 'unassessed'
    identity_only: bool = False
    question_ids: list[str] = Field(default_factory=list,max_length=16)
    checks: dict[str,Literal['matched','mismatch','unknown','not_applicable']]

    @field_validator('checks',mode='before')
    @classmethod
    def conservative_unknown(cls,value):
        # An unexpected assessment label cannot establish support or abort other sources.
        if isinstance(value,dict):return {k:v if v in ('matched','mismatch','unknown','not_applicable') else 'unknown' for k,v in value.items()}
        return value


class EvidenceJudgements(BaseModel):
    judgements: list[EvidenceJudgement] = Field(max_length=40)


class EvidenceCondition(BaseModel):
    source_condition: str
    claim_condition: str
    status: Literal['matched','missing','changed']
    reason: str


class EvidenceScopeJudgement(BaseModel):
    evidence_id: str
    conditions: list[EvidenceCondition]
    scope: Literal['matched','unknown','mismatch']
    reason: str


class EvidenceScopeAudit(BaseModel):
    judgements: list[EvidenceScopeJudgement] = Field(max_length=40)


class AnswerPart(BaseModel):
    request_quote: str
    evidence_ids: list[str]
    status: Literal['answered','missing']
    reason: str


class AnswerListItem(BaseModel):
    source_quote: str
    answer_quote: str
    evidence_ids: list[str]
    covered: bool
    reason: str


class AnswerSourceList(BaseModel):
    source_id: str
    complete_read: bool
    items: list[AnswerListItem]
    reason: str


class AnswerScope(BaseModel):
    question_id: str
    parts: list[AnswerPart]
    enumeration_requested: bool
    source_lists: list[AnswerSourceList]
    complete: bool
    reason: str


class AnswerScopeAudit(BaseModel):
    judgements: list[AnswerScope] = Field(max_length=32)
    read_requests: list[SectionRead] = Field(default_factory=list,max_length=2)


class ScopeDecision(BaseModel):
    id: str
    kind: Literal['blocking','limitation']
    reason: str


class IssueScope(BaseModel):
    decisions: list[ScopeDecision] = Field(max_length=40)


class SearchSelection(BaseModel):
    urls: list[str] = Field(max_length=8)
    reason: str = ''
    decisions: list['CandidateDecision'] = Field(default_factory=list,max_length=32)


class CandidateDecision(BaseModel):
    url: str
    reason: str


class ModelConnection(BaseModel):
    service_id: str
    model: str
    search_protocol: Literal['inherit', 'responses', 'anthropic', 'gemini'] = 'inherit'


class CapabilityTest(BaseModel):
    model: str = Field(min_length=1)
    kind: Literal['text', 'image', 'search']
    protocol: Literal['inherit', 'responses', 'anthropic', 'gemini'] | None = None


class Settings(BaseModel):
    services: list[Service] = []
    default_service: str = ''
    routes: dict[str, Route] = {}
    search: SearchConfig = SearchConfig()
    model_connections: list['ModelConnection'] = Field(default_factory=list)
    default_auto: dict[str, bool] = {s: False for s in STAGES}


class ArticlePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    stage: str = 'setup'
    changes: dict


class ResearchLimits(BaseModel):
    max_calls: int = Field(ge=1,le=100)
    max_pages: int = Field(ge=1,le=500)
    max_rounds: int = Field(ge=0,le=20)


class JobRequest(BaseModel):
    stage: str
    revision: int
    instruction: str = ''
    selected_text: str = ''
    section_id: str = ''
    image_id: str = ''
    chain: bool = True
    issue_ids: list[str] = Field(default_factory=list, max_length=40)
    resume_job_id: str = ''
    action_id: str = ''
    continuation_job_id: str = ''
    research_limits: ResearchLimits | None = None
    research_parent_id: str = ''


ApplicationState = Literal['applied','partial','pending','not_needed']


class IssueAction(BaseModel):
    revision: int
    issue_ids: list[str] = Field(min_length=1,max_length=40)
    action: Literal['verify','waive','bound','bound_auto','exclude','undo','attach']
    action_id: str = Field(min_length=1,max_length=80)
    wording: str = Field(default='', max_length=3000)
    research_limits: ResearchLimits | None = None


SCHEMAS = {'topic': TopicsResult, 'sources': EvidenceResult, 'outline': OutlineResult,
           'review': ReviewResult, 'visual': VisualResult, 'revise': RevisionResult}
