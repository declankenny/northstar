/** Helpers for testing chart code in jsdom. Charts are tested as DOM: ECharts' SVG renderer mounts in jsdom, so a test renders the real
 *  component, looks at the SVG it drew and at the markup it wrote, and drives hover with ECharts' own actions. What jsdom cannot do is
 *  enforce a Content-Security-Policy, so `startCspGuard` watches the ways a style could reach the page that the policy would block. */

/** Give every element a size, which jsdom does not lay out: ECharts sizes a chart by its container. */
export function giveBoxesASize(width = 640, height = 360): () => void {
  const wide = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  const high = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => width });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => height });
  return () => {
    if (wide) Object.defineProperty(HTMLElement.prototype, "clientWidth", wide); else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
    if (high) Object.defineProperty(HTMLElement.prototype, "clientHeight", high); else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
  };
}

const STYLE_ATTRIBUTE = /\bstyle\s*=/i;

/** Where a property is defined: the object on the prototype chain of `from` that owns it. */
function owner(from: object, name: string): object {
  let at: object | null = from;
  while (at && !Object.prototype.hasOwnProperty.call(at, name)) at = Object.getPrototypeOf(at);
  if (!at) throw new Error(`nothing defines ${name}`);
  return at;
}

/** Watch for what the app's policy (`style-src 'self'`) blocks: a `style` attribute written as markup (an HTML string given to
 *  innerHTML, outerHTML or insertAdjacentHTML) or through setAttribute, and a `<style>` element added to the page. Setting a style
 *  through the element's `style` property (CSSOM) is allowed by the policy, and so is not counted. It is the channels that were seen
 *  to be blocked, not the policy itself: it is checked once in a real browser as well. Call `stop()` for what was found. */
export function startCspGuard(): { stop: () => string[] } {
  const found: string[] = [];
  const undo: (() => void)[] = [];
  const note = (channel: string, what: unknown) => found.push(`${channel}: ${String(what).slice(0, 90)}`);

  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (this: Element, name: string, value: string) {
    if (String(name).toLowerCase() === "style") note("setAttribute", value);
    return setAttribute.call(this, name, value);
  };
  undo.push(() => { Element.prototype.setAttribute = setAttribute; });

  for (const name of ["innerHTML", "outerHTML"]) {
    const target = owner(HTMLDivElement.prototype, name);
    const original = Object.getOwnPropertyDescriptor(target, name)!;
    Object.defineProperty(target, name, { ...original, set(this: Element, value: string) {
      if (STYLE_ATTRIBUTE.test(String(value))) note(name, value);
      original.set!.call(this, value);
    } });
    undo.push(() => Object.defineProperty(target, name, original));
  }

  const insert = Element.prototype.insertAdjacentHTML;
  Element.prototype.insertAdjacentHTML = function (this: Element, where: InsertPosition, html: string) {
    if (STYLE_ATTRIBUTE.test(html)) note("insertAdjacentHTML", html);
    return insert.call(this, where, html);
  };
  undo.push(() => { Element.prototype.insertAdjacentHTML = insert; });

  const styleElements = document.querySelectorAll("style").length;
  return {
    stop() {
      undo.forEach((restore) => restore());
      if (document.querySelectorAll("style").length > styleElements) note("<style> element", "added to the page");
      return found;
    },
  };
}
