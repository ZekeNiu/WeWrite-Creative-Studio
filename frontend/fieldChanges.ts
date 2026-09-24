// Fields register their pending edits so navigation can wait for a successful save.
const fields = new Set<() => Promise<void>>();
const dirty = new Map<() => Promise<void>, () => boolean>();
const listeners = new Set<() => void>();
export function hasDirtyFields(){return [...dirty.values()].some(check=>check())}
window.addEventListener('beforeunload',e=>{if(hasDirtyFields()){e.preventDefault();e.returnValue=''}});
export function notifyFields(){listeners.forEach(fn=>fn())}
export function watchFields(fn:()=>void){listeners.add(fn);return ()=>{listeners.delete(fn)}}
export function registerField(flush: () => Promise<void>, check=()=>false) {
  fields.add(flush);
  dirty.set(flush,check);
  return () => { fields.delete(flush);dirty.delete(flush);notifyFields(); };
}
export async function flushFields() {
  for (const flush of [...fields]) await flush();
}
