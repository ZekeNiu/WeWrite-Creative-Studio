import type {Source} from './types';
const labels:Record<string,string>={design:'研究设计',results:'主要结果',counterevidence:'反证',limitations:'局限',scope:'适用范围'};
export default function SourceNotebook({source:s}:{source:Source}){
 const n=s.notebook;if(!n)return null;
 return <details className="material-relations"><summary>逐源阅读笔记 · {n.notes.length} 条</summary><p className="muted">笔记对应已取得的原文。未记录某类信息不代表原文不存在；摘要笔记不能代表全文。</p>{n.read_characters!==undefined&&<p>分析已覆盖 {n.read_characters} / {n.total_characters} 字符；其余原文仍保留，可按问题回读。</p>}{n.notes.map((x,i)=><details key={i}><summary>{labels[x.category]||x.category} · {x.note}</summary><blockquote>{x.quote}</blockquote><small>原文字符 {x.start+1}—{x.end}</small></details>)}{n.missing_categories.length>0&&<p className="muted">尚无定位笔记：{n.missing_categories.map(x=>labels[x]||x).join('、')}</p>}{n.pointers?.length>0&&<details><summary>表格、脚注及补充材料线索</summary>{n.pointers.map((x,i)=><p key={i}>{x.label} · 字符 {x.start+1}</p>)}</details>}</details>;
}
