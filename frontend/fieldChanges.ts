// Fields register their pending edits so navigation can wait for a successful save.
const fields = new Set<() => Promise<void>>();
export function registerField(flush: () => Promise<void>) {
  fields.add(flush);
  return () => { fields.delete(flush); };
}
export async function flushFields() {
  for (const flush of [...fields]) await flush();
}
