/** What a person's choice of columns is made of, apart from how it is drawn: moving one, and what to tell the server when the
 *  drawer is applied. The server checks every request again; this is so the drawer never offers what would be refused. */

/** A new order with the column at `from` moved to `to`. The same array when nothing moves, or when either place is outside it. */
export function moved(keys: string[], from: number, to: number): string[] {
  if (from === to || from < 0 || to < 0 || from >= keys.length || to >= keys.length) return keys;
  const next = keys.slice();
  const [key] = next.splice(from, 1);
  next.splice(to, 0, key);
  return next;
}

export const sameColumns = (a: string[], b: string[]) => a.length === b.length && a.every((key, i) => key === b[i]);

/** What applying the drawer asks of the server: nothing (`undefined`) when the columns are as they were, `null` to forget the choice
 *  when the draft is the list's own columns again, otherwise the columns. A choice that happens to equal the default is not kept, so
 *  a list that later gains a default column still gives it to the person who never chose differently. */
export function columnChoice(draft: string[], shown: string[], defaults: string[]): string[] | null | undefined {
  if (sameColumns(draft, shown)) return undefined;
  return sameColumns(draft, defaults) ? null : draft;
}
