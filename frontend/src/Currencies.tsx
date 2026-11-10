import { ListView } from "./ListView";

/** The admin page listing the currency catalog as it is stored, with how many accounts use each. It is a list of the framework, so
 *  this page is its heading and the table: a person searches it, filters it (Enabled, or in use with Accounts at least 1), sorts it and
 *  exports it like any other. It does not know which currency is the system currency. A currency's code opens its page, where it is
 *  switched on or off and its rates are kept. */
export function Currencies() {
  return (
    <div className="page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>Currencies</h1>
          <p className="sub">The ISO 4217 catalog. A currency can be used for new accounts when it is enabled.</p>
        </div>
      </div>
      <ListView listKey="currencies" config={{ title: "Currencies", isAdmin: true, emptyText: "There are no currencies." }} />
    </div>
  );
}
