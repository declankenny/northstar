import { createContext } from "react";

/** Ask the signed-in shell to load the person's details again. A page calls it when something it did showed them out of date:
 *  a refused save because their number and date format was changed elsewhere, so the page reads the draft in the new one. */
export const RefreshMe = createContext<() => void>(() => {});
