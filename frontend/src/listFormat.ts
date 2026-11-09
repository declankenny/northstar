import type { ListColumn } from "./api";
import { formatDate } from "./dates";
import { getLocale, formatInteger } from "./locale";
import { formatCents } from "./money";

/** A whole number holding a decimal with `scale` places (hundredths of a degree for 2), written in the person's number format. */
export function formatScaled(value: number, scale: number): string {
  const abs = Math.abs(value);
  const whole = formatInteger(Math.floor(abs / 10 ** scale));
  const fraction = scale === 0 ? "" : getLocale().decimal_mark + String(abs % 10 ** scale).padStart(scale, "0");
  return (value < 0 ? "-" : "") + whole + fraction;
}

type Amount = { value: number; scale: number; unit: string | null };

/** What a cell shows for a value, written in the person's formats, or null when there is nothing to show. A timestamp is shown as
 *  its UTC date, the way the rest of the app shows when something was made. */
export function formatCell(column: ListColumn, value: unknown): string | null {
  if (value === null || value === undefined) return null;
  switch (column.kind) {
    case "integer": return formatInteger(value as number);
    case "number": return String(value).replace(".", getLocale().decimal_mark);
    case "decimal": return column.scale === null ? String(value) : formatScaled(value as number, column.scale);
    case "date": return formatDate(value as string);
    case "timestamp": return formatDate((value as string).slice(0, 10));
    case "yes_no": return value === 1 ? "Yes" : "No";
    case "amount": {
      const amount = value as Amount;
      return amount.unit === null ? formatScaled(amount.value, amount.scale)
        : formatCents(amount.value, { code: amount.unit, name: amount.unit, minor_units: amount.scale });
    }
    default: return String(value);
  }
}

/** Numbers are lined up on the right, so a column of them can be compared by eye. */
export const isNumeric = (column: ListColumn) => ["integer", "number", "decimal", "amount"].includes(column.kind);
