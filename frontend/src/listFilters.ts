import type { Choices, Condition, FieldNode, FieldTree } from "./api";
import { formatDate } from "./dates";
import { getLocale, normalizeGroupMarks } from "./locale";

/** What a filter is made of, apart from how it is drawn: which operators take which value, whether a typed condition is complete,
 *  how it is written for the server, and how a chip says it. The server checks every condition again; this is so a person is told
 *  what is wrong before Apply, in the words the server uses. */

/** Every column the list offers, relations included and what lies below them: the one flat list the conditions refer to. */
export function flatten(tree: FieldTree | null | undefined): FieldNode[] {
  if (!tree) return [];
  return [...tree.fields, ...tree.relations.flatMap((r) => [r, ...flatten(r.children)])];
}

const NO_VALUE = new Set(["is_empty", "is_not_empty", "is_yes", "is_no"]);
const RANGE = "between";
export const takesNoValue = (operator: string) => NO_VALUE.has(operator);
export const isRange = (operator: string) => operator === RANGE;
export const isNumberKind = (kind: FieldNode["kind"]) => ["integer", "number", "decimal", "amount"].includes(kind);
export const isDateKind = (kind: FieldNode["kind"]) => kind === "date" || kind === "timestamp";

/** The value a new or changed operator starts with: nothing, an empty box, two empty boxes, or no choices. */
function startValue(node: FieldNode, operator: string): unknown {
  if (takesNoValue(operator)) return undefined;
  if (node.choices !== null) return [];
  return isRange(operator) ? ["", ""] : "";
}

export function startCondition(node: FieldNode): Condition {
  const operator = node.operators[0]?.name ?? "";
  return withValue({ field: node.key, operator }, startValue(node, operator));
}

function withValue(condition: Condition, value: unknown): Condition {
  return value === undefined ? { field: condition.field, operator: condition.operator } : { ...condition, value };
}

/** Changing the operator keeps what was typed when it still fits (a number stays a number) and starts afresh when it does not. */
export function withOperator(node: FieldNode, condition: Condition, operator: string): Condition {
  const kept = condition.value;
  const fits = (isRange(condition.operator) === isRange(operator)) && !takesNoValue(condition.operator) && !takesNoValue(operator);
  return withValue({ field: condition.field, operator }, fits ? kept : startValue(node, operator));
}

/** A typed number as the server reads it ("1234.5" with a point, no group marks), or why it cannot be one. `places` is how many
 *  decimal places the column can have (null: any); a typed value with more is refused, never rounded. */
export function readNumber(text: string, places: number | null): { number: string } | { message: string } {
  const { decimal_mark: decimal, group_mark: group } = getLocale();
  let s = text.trim();
  if (s === "") return { message: "Type a number." };
  const negative = s.startsWith("-");
  if (negative) s = s.slice(1);
  s = normalizeGroupMarks(s, group);
  const at = s.indexOf(decimal);
  const whole = (at < 0 ? s : s.slice(0, at));
  const fraction = at < 0 ? "" : s.slice(at + decimal.length);
  const grouped = new RegExp(`^(?:\\d{1,3}(?:${group.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\d{3})+|\\d+)$`);
  if (!grouped.test(whole) || (at >= 0 && !/^\d+$/.test(fraction)) || whole.length + fraction.length > 18) return { message: "Type a number." };
  if (places !== null && fraction.length > places) {
    return { message: places === 0 ? "Type a whole number." : `Use at most ${places} decimal places.` };
  }
  const digits = whole.split(group).join("");
  const number = `${negative ? "-" : ""}${digits}${fraction === "" ? "" : `.${fraction}`}`;
  return { number };
}

/** How many decimal places a typed value may have for this kind of column. */
function placesFor(node: FieldNode): number | null {
  switch (node.kind) {
    case "integer": return 0;
    case "decimal": return node.scale ?? 0;
    case "amount": return 3;
    default: return null;
  }
}

/** A real calendar day as YYYY-MM-DD. Date.parse alone accepts 2026-02-30 (as March 2), so the day must read back as itself. */
const isDay = (text: unknown): text is string => {
  if (typeof text !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === text;
};

/** Why a condition cannot be applied yet, or null when it is complete. */
export function problem(node: FieldNode, condition: Condition): string | null {
  const { operator, value } = condition;
  if (!node.operators.some((o) => o.name === operator)) return "Choose how to compare.";
  if (takesNoValue(operator)) return null;
  if (node.choices !== null) return Array.isArray(value) && value.length > 0 ? null : "Choose at least one value.";
  const parts = isRange(operator) ? (Array.isArray(value) && value.length === 2 ? value : null) : [value];
  if (parts === null) return "Give the two ends of the range.";
  if (isDateKind(node.kind)) {
    if (!parts.every(isDay)) return "Choose a real date.";
    if (parts.length === 2 && String(parts[0]) > String(parts[1])) return "The range ends before it starts.";
    return null;
  }
  if (isNumberKind(node.kind)) {
    const read = parts.map((part) => readNumber(String(part ?? ""), placesFor(node)));
    const bad = read.find((r): r is { message: string } => "message" in r);
    if (bad) return bad.message;
    if (parts.length === 2 && Number((read[0] as { number: string }).number) > Number((read[1] as { number: string }).number)) {
      return "The range ends before it starts.";
    }
    return null;
  }
  const text = typeof value === "string" ? value : "";
  if (text.trim() === "") return "Type the text to look for.";
  return text.length > 256 ? "That text is too long to filter by." : null;
}

/** The condition as the server reads it: numbers with a point, text as typed, and no value where the operator takes none. */
export function toWire(node: FieldNode | undefined, condition: Condition): Condition {
  const { field, operator, value } = condition;
  if (takesNoValue(operator) || value === undefined) return { field, operator };
  if (node && isNumberKind(node.kind)) {
    const convert = (part: unknown) => {
      const read = readNumber(String(part ?? ""), null);
      return "number" in read ? read.number : String(part ?? "");
    };
    return { field, operator, value: Array.isArray(value) ? value.map(convert) : convert(value) };
  }
  return { field, operator, value };
}

/** Whether two sets of conditions mean the same filter, whatever the order they are listed in or the way a number was typed. */
export function sameConditions(a: Condition[], b: Condition[], nodes: Map<string, FieldNode>): boolean {
  const key = (list: Condition[]) => JSON.stringify(list.map((c) => toWire(nodes.get(c.field), c)).sort((x, y) => x.field.localeCompare(y.field)));
  return key(a) === key(b);
}

/** A condition as a chip says it: “Account type is any of Savings, Checking”. `choices` names what a relation's ids stand for. */
export function describe(node: FieldNode | undefined, condition: Condition, choices?: Choices): string {
  const name = node?.path_label ?? condition.field;
  const operator = node?.operators.find((o) => o.name === condition.operator)?.label ?? condition.operator;
  const { value } = condition;
  if (takesNoValue(condition.operator) || value === undefined) return `${name} ${operator}`;
  const show = (part: unknown) => {
    if (node && isDateKind(node.kind)) return formatDate(String(part).slice(0, 10));
    if (node && isNumberKind(node.kind)) return String(part).replace(".", getLocale().decimal_mark);
    return String(part);
  };
  if (Array.isArray(value)) {
    if (node?.choices !== null && node?.choices !== undefined) {
      const names = new Map((choices?.options ?? []).map((o) => [o.id, o.value]));
      const labels = value.map((v) => (typeof v === "number" ? names.get(v) : v));
      return labels.every((l) => l !== undefined) ? `${name} ${operator} ${labels.join(", ")}` : `${name} ${operator} ${value.length} selected`;
    }
    return `${name} ${operator} ${value.map(show).join(" and ")}`;
  }
  return `${name} ${operator} ${show(value)}`;
}
