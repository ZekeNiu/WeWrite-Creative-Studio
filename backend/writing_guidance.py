"""Application writing guidance, shared by native and compatibility entry points.

These instructions govern manuscript composition, not source verification. Keep
the upstream skills intact and select by task purpose, never by model route.
"""
import hashlib

VERSION = '1'

COMMON = '''公众号创作约定：围绕本篇读者问题，把想表达的内容讲完整、讲顺、讲得有吸引力。本次明确要求、选定立意和账号声音决定文章的方向。
主张是要表达的内容；证据条件帮助你把主张写准确；核查记录供回查。内部提醒、检索过程、未采用内容和写作指令留在工作记录中。旧大纲里夹带的作者提醒也按指导信息理解，不作为正文要点展开。
按整篇论述组织观点、例子和转折，让后一段接住前一段。可以使用有解释力的类比、洞察、悬念和鲜明判断；区分表达手法与事实断言，保持事实及其证据强度，不补造经历或研究结果。
反方观点和具体条件在推进论证、解释差异或改变读者选择时自然展开。已有适用对象可直接写入主张，不必在段末反复提醒“不能一概而论”“还需要结合具体情况”。这些词不是禁词；处理的是没有新增内容、只为防备假想质疑而插入的说明。
需要修正时，优先把原句写准确并接回上下文。非核心的无据细节自行修正或省去；证据使核心立意无法成立时，在任务说明中交代并请求决定，不以免责段落掩盖问题或静默换题。'''

STAGES = {
    'sources': '素材整理：围绕原本要回答的问题形成可用于文章的主张。text 写清来源支持的内容，boundary 保留影响该主张的具体条件；核查过程和对作者的提醒留在任务记录中。补充检索线索不自动变成文章必须回答的新问题。',
    'outline': '大纲：每节承担一个明确的叙述任务，title、purpose、points 描述本篇要讲的内容及其推进关系。写作约束归入任务书的约束部分；反方、机制、局限按论述需要安排，结构参考不用逐格填满。保留用户确认的切入点与新增价值。',
    'write': '初稿：沿已确认的主线完整展开，按读者的理解顺序安排证据和解释。不要把主张清单逐条改写成“观点加限制”的段落。自读时检查段落承接、论述是否被无关解释打断，以及结尾是否完成本篇承诺；保留有辨识度的语气和表达。',
    'review': '审稿：先读整篇的主线、推进和声音，再针对正文中实际存在的问题修改。事实问题指明具体主张与依据；表达问题指明实际影响阅读的位置，不为假想误解追加说明。修准说法后通读前后段，保留有价值的反方、具体条件与表达特色。修改记录放入编辑报告，不写入正文；沿用当前审稿轮次与候选交接。',
    'revise': '修改：严格遵守本次要求与选段范围，保留段落在原文中的作用、语气和衔接。只交付需要的替换文本；没有要求整篇重构时，不把局部修改扩展为新的研究或通篇审稿。',
    'rewrite': '平台改写：围绕原稿的核心内容适配目标平台节奏，保留观点、具体事实条件和原稿声音；内部审核说明不成为新平台的文案。',
}
STAGES['edit'] = STAGES['review']


def instructions(purpose):
    stage = STAGES.get(purpose)
    return COMMON + '\n' + stage if stage else ''


def metadata(purpose):
    text = instructions(purpose)
    return dict(version=VERSION, purpose=purpose, sha256=hashlib.sha256(text.encode('utf-8')).hexdigest()) if text else None
