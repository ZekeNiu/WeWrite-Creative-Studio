import {type Article,type Meta,type Save} from './types';
import {Field,Select} from './ui';

export default function BriefPanel({a,meta,save}:{a:Article;meta:Meta;save:Save}){
 const update=(key:string,value:string|number)=>void save({brief:{...a.brief,[key]:value}},'setup');
 const persona=meta.personas.find(x=>x.id===a.brief.persona);
 return <div className="brief-panel"><Select label="常用栏目" value={a.brief.column} onChange={v=>update('column',v)}><option>运动科学</option><option>运动健康</option><option>AI</option></Select><Field label="这次想探索的领域" value={a.brief.domain} placeholder="如：青少年体能、AI 教育应用…" onCommit={v=>update('domain',v)}/><Field label="指定主题（可选）" value={a.brief.topic} placeholder="有题目就直接填，跳过 AI 选题" onCommit={v=>update('topic',v)}/>
 <Select label="目标读者" value={a.brief.audience} onChange={v=>void save({brief:{...a.brief,audience:v,words:v==='专业解读'?2500:1800}},'setup')}><option>大众科普</option><option>专业解读</option></Select><Field label="目标篇幅 / 字" type="number" min={200} max={15000} value={a.brief.words} onCommit={v=>update('words',Number(v))}/><Select label="写作人格" value={a.brief.persona} onChange={v=>update('persona',v)}>{meta.personas.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</Select>{persona&&<div className="persona-note"><p>{persona.description}</p><q>{persona.example}</q></div>}
 <details><summary>更细致的写作要求</summary><Field label="读完希望解决什么问题" multiline value={a.brief.purpose} onCommit={v=>update('purpose',v)}/><Field label="语气与表达偏好" multiline value={a.brief.tone} onCommit={v=>update('tone',v)}/><Field label="必须包含" multiline value={a.brief.include} onCommit={v=>update('include',v)}/><Field label="避免使用" multiline value={a.brief.avoid} onCommit={v=>update('avoid',v)}/><Field label="资料时效 / 天" type="number" value={a.brief.recent_days} onCommit={v=>update('recent_days',Number(v))}/></details></div>
}
