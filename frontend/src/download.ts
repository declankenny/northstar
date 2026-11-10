/** Hand the browser a file it already has, as a download with this name. The page stays where it is. */
export function saveFile(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);   // after the browser has taken it
}

/** The file name the server gave a download (`attachment; filename="x.csv"`), or `fallback` when it gave none. */
export function fileNameOf(disposition: string | null, fallback: string): string {
  return /filename="([^"]+)"/.exec(disposition ?? "")?.[1] ?? fallback;
}
