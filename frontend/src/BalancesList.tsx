import { ListView } from "./ListView";

/** Every live balance across all accounts. A list is data on the server (its columns, sort and filters), so this page is only a
 *  heading and the table. */
export function BalancesList({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="acct">
      <div className="top"><div><h1>Balances</h1></div></div>
      <ListView listKey="balances" config={{ title: "Balances", isAdmin, emptyText: "There are no balances yet. Add one from Update balances." }} />
    </div>
  );
}
