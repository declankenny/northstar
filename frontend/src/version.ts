/** How the version shows in the navigation: v0.1.0. Nothing until it has loaded. */
export function versionLabel(version: string | null): string {
  return version ? `v${version}` : "";
}
