/** One notice for the next page: a page that sends the person somewhere else leaves it here, and that page reads it and then clears it once it
 *  has shown. It lives in memory only, so a reload shows nothing, and an address opened afresh never carries one. */
let message: string | null = null;

export function setFlash(text: string): void {
  message = text;
}

/** The waiting notice, left in place so that reading it twice (React's development double render) gives the same answer. */
export function peekFlash(): string | null {
  return message;
}

export function clearFlash(): void {
  message = null;
}
