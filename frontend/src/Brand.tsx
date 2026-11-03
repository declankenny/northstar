/** The brand mark and name. Both variants are in the page and the stylesheet shows the one for the user's theme (data-theme). */
export function Brand() {
  return (
    <div className="brand">
      <img className="mark mark-light" src="/static/brand-light.svg" alt="" width={30} height={30} />
      <img className="mark mark-dark" src="/static/brand-dark.svg" alt="" width={30} height={30} />
      Northstar
    </div>
  );
}
