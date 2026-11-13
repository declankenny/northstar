import { SLOTS } from "./theme";

/** The categorical colour slot (1 to SLOTS) of an entity, from its id alone: `(id - 1) mod SLOTS`, counted from 1.
 *
 *  It does not depend on the entity's size, its place in a chart, what else is shown, the report or the filters, so an entity is the same
 *  colour wherever it appears, and nothing is stored on a record. The first SLOTS entities of a kind never share a colour (ids are
 *  auto-incremented and never reused, so they are dense), and past that the colours repeat, in order. `kind` names what the id is the id
 *  of ("account_type", "account") and is a separate namespace: it is never mixed into the slot, because ids of one kind are what spread
 *  evenly, and a hash of the pair would make two of five entities share a colour about half the time.
 *
 *  Changing SLOTS, the order of the palette or this calculation changes the colour of what already exists, so it is a deliberate,
 *  versioned change (docs/decisions.md, "Chart colours are one fixed palette ..."). An id that is not a whole number from 1, or an empty
 *  kind, has no colour (undefined), which a chart draws in the muted colour. */
export function slotFor(kind: string, id: number): number | undefined {
  if (kind === "" || !Number.isInteger(id) || id < 1) return undefined;
  return ((id - 1) % SLOTS) + 1;
}
