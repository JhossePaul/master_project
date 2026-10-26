/** Lee un token de tokens.css (nombre de variable CSS). */
export function cssVar(
  name: string,
  el: Element = document.documentElement,
): string {
  return getComputedStyle(el).getPropertyValue(name).trim();
}
