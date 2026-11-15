/** An account's website (#266): the text of its link and the words that say what saving cleaned out of it. */

/** The site's name for a link: its host without a leading "www.", or the address itself when it cannot be read as one. */
export function siteName(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** What a screen reader hears for the link: the visible text first, so voice control matches what is on screen, then what it opens.
 *  `account` is left out when the list does not carry the account's name. */
export function websiteLabel(url: string, account?: string): string {
  return `${siteName(url)} — Open ${account ? `${account}'s` : "the account's"} website (opens in a new tab)`;
}

const REMOVED: Record<string, string> = {
  login: "the sign-in details",
  query: "the part after “?”",
  fragment: "the part after “#”",
};

/** The notice after a save that cleaned the address, or null when nothing was removed. */
export function websiteRemovedNotice(removed: string[]): string | null {
  const parts = removed.map((key) => REMOVED[key]).filter(Boolean);
  if (parts.length === 0) return null;
  const said = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `Saved. The website was saved without ${said}, which can carry a sign-in token.`;
}
