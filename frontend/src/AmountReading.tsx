import { formatCents, readAmount } from "./money";

/** The line under an amount box that says how what is typed is read: "Reads as 1.234,56 EUR", or why it cannot be read. It is
 *  empty until something is typed, and it announces its changes. It uses the same rules as the server, in the person's
 *  locale and the amount's currency. */
export function AmountReading({ text }: { text: string }) {
  const reading = readAmount(text);
  return (
    <div className={reading && "message" in reading ? "reads bad" : "reads ok"} aria-live="polite">
      {reading && ("message" in reading ? reading.message : `Reads as ${formatCents(reading.cents)}`)}
    </div>
  );
}
