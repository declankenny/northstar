# Row actions: a review of the existing lists

Done for [#272](https://github.com/declankenny/northstar/issues/272) before step 2 and agreed on November 14, 2026. A list declares its actions once, as an array in its `ListConfig`: one action is drawn as a button in the row, two or more as the "⋯" menu, and each action says per row whether it applies (`show`) and why it is unavailable (`disabled`). Not the spec or the decisions log: the decision is in `docs/decisions.md` with step 2.

| Where | Today | Declared actions | Context rules |
| --- | --- | --- | --- |
| Balances list | none: the date opens the page | none | none |
| Accounts list | none (#222 stays in the backlog) | none | none |
| Currencies list | none: the code opens the page | none | none |
| Account page's balance list | none: the date opens the page | none | none |
| Balance history | none before step 2 | **Restore** (one action, so a button) | absent on the current row and on a note-only change (`restorable` is 0); greyed out on a closed account and while the form has unsaved changes |
| Users (hand-built table) | `RowMenu`: Edit, Reset password, Delete | unchanged, three actions, so the menu | your own row shows only Edit |
| Account types (hand-built table) | `RowMenu`: Edit, Delete | unchanged, two actions, so the menu | Delete is greyed out while any account uses the type, with the reason |
| Imports register (hand-built table) | an **Undo** button on each row | unchanged: already a single button | absent once undone |

Later screens follow the rule: Deleted accounts (**Restore account**) and Deleted balances (**Restore balance**) each declare one action, so each draws a button.

No list needed retrofitting. The hand-built tables are not framework lists and keep using `RowMenu` directly.
