// Apply the saved theme before the first paint, so a light-mode user never sees a dark flash. Shared by the
// sign-in page and the React app. It is a file, not an inline script, because the content security policy
// allows no inline scripts. It must stay a plain script (no import or export) loaded in the head.
try {
  var saved = localStorage.getItem("northstar-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch (e) {
  // Storage can be blocked: the page then keeps its default theme.
}
