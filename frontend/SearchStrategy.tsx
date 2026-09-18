export const SEARCH_PREFERENCES:Record<string,string>={auto:'自动选择',native:'模型联网优先',tavily:'Tavily 优先',browser:'浏览器优先'};
const CHANNELS:Record<string,string>={native:'模型联网',tavily:'Tavily',google:'浏览器 · Google',bing:'浏览器 · Bing',baidu:'浏览器 · 百度',duckduckgo:'浏览器 · DuckDuckGo',openalex:'OpenAlex',pubmed:'PubMed / PMC',arxiv:'arXiv',crossref:'Crossref'};
export interface Strategy {preference:string;allow_fallback:boolean;attempted:string[];used:string[];issue?:string}
export default function SearchStrategy({value}:{value?:Strategy}){
 if(!value)return null;
 const names=(ids:string[])=>ids.map(x=>CHANNELS[x]||x).join('、');
 return <div className="search-strategy small-text"><p>本次设置：{SEARCH_PREFERENCES[value.preference]||value.preference} · {value.allow_fallback?'允许自动切换':'不切换其他方式'}</p><p>取得检索结果：{value.used.length?names(value.used):'尚未取得'}（含缓存）</p>{value.attempted.length>0&&<p className="muted">实际请求：{names(value.attempted)}</p>}{value.issue&&<p className="notice amber">{value.issue}</p>}</div>
}
