const names:Record<string,string>={
 viewpoint:'观点',usefulness:'用途',voice:'声音',
 task_alignment:'任务对齐',alignment:'任务对齐',factual_accuracy:'事实准确性',accuracy:'准确性',facts:'事实依据',
 evidence:'证据支持',sources:'来源依据',depth:'内容深度',clarity:'表达清晰度',naturalness:'表达自然度',
 structure:'文章结构',boundaries:'适用边界',originality:'原创表达',readability:'可读性',
 sentence_length_stddev:'句长变化',sentence_length_range:'长短句搭配',paragraph_length_variance:'段落节奏',
 vocabulary_richness:'词汇多样性',emotional_balance:'情绪表达',adverb_density:'副词密度',banned_words:'套话检查',
 sentence_integrity:'句子完整性',real_sources:'来源表述线索',register_consistency:'语体一致性',insertion_control:'插入语控制',
};
function description(value:unknown){
 if(typeof value!=='string')return '暂无检查说明';
 const translations:[RegExp,string][]=[[/calibrated from/g,'校准前'],[/center=/g,'参考中心值：'],[/stddev=/g,'句长标准差：'],[/target ≥/g,'参考值 ≥'],[/range=/g,'句长跨度：'],[/short_paras=/g,'短段落数：'],[/consecutive similar-length pairs/g,'组相邻段落长度接近'],[/bigram_ttr=/g,'双字词多样性：'],[/negative markers=/g,'负向表达标记：'],[/density=/g,'副词数量：'],[/\/100chars/g,'／每百字'],[/consecutive_starts=/g,'连续副词开头：'],[/0 banned words/g,'未发现预设套话'],[/found:/g,'处套话：'],[/possible fragments/g,'处疑似不完整句'],[/soft allowance/g,'参考容许值'],[/source-attribution signals \(not fact verification\)/g,'处来源表述线索（不代表事实已核实）'],[/heavily used vocabulary bands=/g,'高频语体类别：'],[/self-corrections\/insertions/g,'处自我修正或插入语'],[/too few sentences(?: to measure)?/gi,'句子数量不足，暂不足以评估'],[/too few paragraphs/gi,'段落数量不足'],[/too few CJK characters/gi,'中文字数不足'],[/no sentences/gi,'没有可检查的句子'],[/text too short/gi,'内容过短'],[/too short/gi,'内容过短']];
 return translations.reduce((s,[from,to])=>s.replace(from,to),value);
}
const numeric=(value:unknown)=>typeof value==='number'&&Number.isFinite(value);
export default function ReviewChecks({review}:{review:any}){
 const hints=review.tool_hints||{};
 const quality=numeric(hints.quality_score)?hints.quality_score:numeric(hints.composite_score)?100-hints.composite_score:null;
 const dimensions=Object.entries(review.dimensions||{});
 const checks=Object.entries({...hints.tier1,...hints.tier2}).filter(([key])=>!key.startsWith('_'));
 return <details className="review-checks"><summary>查看辅助评分与机械检查</summary>
  <p className="muted small-text">这些分数仅辅助检查表达，不代表事实准确率，也不是 AI 检测概率。机械检查分数越高，表示越符合该项参考规则。</p>
  <h4>编辑维度</h4>{dimensions.length?<div className="review-dimensions">{dimensions.map(([key,value])=><div key={key}><span>{names[key]||key}</span><strong>{numeric(value)?String(value)+(review.quality_version?' / 5':''):'暂无评分'}</strong></div>)}</div>:<p className="muted">暂无编辑维度评分。</p>}
  {review.fact_audit&&<details><summary>独立事实核查 · {review.fact_audit.complete?'已检查全部段落':'仍有段落待核查'}</summary>{review.fact_audit.segments?.map((s:any)=><div key={s.segment_id}>{s.status==='no_factual_claim'?<p className="muted">{s.reason}</p>:s.facts?.map((f:any,i:number)=><details key={i}><summary>{f.quote}</summary><p>{f.reason}</p><p>{f.boundary}</p>{f.source_quote&&<blockquote>{f.source_quote}</blockquote>}<p className="muted">{['supported','limited'].includes(f.checked_status)?'来源已核对':'仍需处理'}</p></details>)}</div>)}</details>}
  <h4>机械检查</h4><p>表达参考分：<strong>{quality===null?'暂无评分':`${Number(quality).toFixed(1)} / 100`}</strong>{numeric(hints.char_count)&&<span className="muted"> · 已检查 {hints.char_count} 字</span>}</p>
  {checks.length?checks.map(([key,value])=>{const row=value as any;return <article className="review-check" key={key}><div className="row between"><strong>{names[key]||key}</strong><span>{numeric(row?.score)?`${(row.score*100).toFixed(0)} / 100`:'暂无评分'}</span></div><p>{description(row?.detail)}</p></article>}):<p className="muted">暂无机械检查结果。</p>}
 </details>;
}
