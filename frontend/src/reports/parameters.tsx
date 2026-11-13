import { isDay } from "../listFilters";
import type { ReportDefinition, ReportParameter } from "./types";

/** What a person has typed or chosen for each parameter, by key. Everything is text until it is sent, so a date half typed or a number
 *  with a stray letter can be kept and pointed at instead of being lost. */
export type Values = Record<string, string>;

/** Every parameter at the default the server resolved (it reads its own clock, so the page never reads the browser's). */
export const initialValues = (definition: ReportDefinition): Values => Object.fromEntries(definition.parameters.map((p) => [p.key, String(p.default)]));

/** The values as a request carries them: a whole number as a number, everything else as the text it is. Call it only when `problems`
 *  finds none. */
export function parametersFor(definition: ReportDefinition, values: Values): Record<string, string | number> {
  return Object.fromEntries(definition.parameters.map((p) => [p.key, p.kind === "integer" ? Number(values[p.key]) : values[p.key]]));
}

function problem(p: ReportParameter, values: Values, definition: ReportDefinition): string | null {
  const text = values[p.key] ?? "";
  const labelOf = (key: string) => definition.parameters.find((q) => q.key === key)?.label ?? key;
  if (p.kind === "date") {
    if (!isDay(text)) return "Choose a real date.";
    for (const rule of p.rules) {
      if (rule.rule === "not_future" && text > definition.today) return "Choose today or an earlier date. A report cannot look into the future.";
      const other = rule.rule === "not_future" ? "" : values[rule.other] ?? "";
      if (rule.rule === "after" && isDay(other) && text <= other) return `${p.label} must be after ${labelOf(rule.other)}.`;
      if (rule.rule === "on_or_after" && isDay(other) && text < other) return `${p.label} must be on or after ${labelOf(rule.other)}.`;
    }
    return null;
  }
  if (p.kind === "choice") return p.choices.some((c) => c.value === text) ? null : "Choose one of the options.";
  if (!/^-?\d+$/.test(text.trim())) return "Enter a whole number.";
  const n = Number(text);
  if (p.minimum !== null && p.maximum !== null && (n < p.minimum || n > p.maximum)) return `Enter a number from ${p.minimum} to ${p.maximum}.`;
  if (p.minimum !== null && n < p.minimum) return `Enter a number of ${p.minimum} or more.`;
  if (p.maximum !== null && n > p.maximum) return `Enter a number of ${p.maximum} or less.`;
  return null;
}

/** What is wrong with each parameter, or null, by key. The server checks every one again; this is so that nothing is asked for
 *  that cannot be answered, and a person is told why at once. */
export function problems(definition: ReportDefinition, values: Values): Record<string, string | null> {
  return Object.fromEntries(definition.parameters.map((p) => [p.key, problem(p, values, definition)]));
}

/** The controls the definition declares, each with its label, in the report's own order. A parameter's control follows its kind. */
export function ParameterControls({ definition, values, errors, onChange }: {
  definition: ReportDefinition; values: Values; errors: Record<string, string | null>; onChange: (key: string, value: string) => void;
}) {
  return (
    <>
      {definition.parameters.map((p) => (
        <label className="rp-field" key={p.key}><span>{p.label}</span>
          {p.kind === "date" && (
            <input type="date" value={values[p.key]} className={errors[p.key] ? "bad" : undefined} aria-invalid={errors[p.key] ? true : undefined}
              onChange={(e) => onChange(p.key, e.target.value)} />
          )}
          {p.kind === "choice" && (
            <select value={values[p.key]} onChange={(e) => onChange(p.key, e.target.value)}>
              {p.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          )}
          {p.kind === "integer" && (
            <input inputMode="numeric" value={values[p.key]} className={errors[p.key] ? "bad" : undefined} aria-invalid={errors[p.key] ? true : undefined}
              onChange={(e) => onChange(p.key, e.target.value)} />
          )}
        </label>
      ))}
    </>
  );
}
