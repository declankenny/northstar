import { useEffect, useRef, useState } from "react";
import { fetchProperties, type PropertyRow, saveProperty } from "./api";
import { useRequest } from "./useRequest";

const groupOf = (p: PropertyRow) => p.name.split(".")[0];
/** A group's heading is its name with a capital, except the ones that are initials. */
const INITIALS = new Set(["ui", "oidc"]);
const title = (group: string) => (INITIALS.has(group) ? group.toUpperCase() : group.charAt(0).toUpperCase() + group.slice(1));
const stored = (p: PropertyRow) => p.value ?? "";
const SYSTEM_CURRENCY = "system.currency";
const LOCALE_DEFAULT = "ui.locale.default";

/** The admin page for the installation's settings: a list of groups on the left, the chosen group's properties on the right.
 *  What a person has typed stays as a draft until it is saved or reverted, and leaving a group with drafts asks first. */
export function SystemProperties({ onCurrencyChange }: { onCurrencyChange?: () => void } = {}) {
  const { data: list, error, setData: setList } = useRequest(fetchProperties, []);
  const [chosen, setChosen] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [wanted, setWanted] = useState<string | null>(null); // the group to open once the edits in this one are discarded
  const [shown, setShown] = useState<Record<string, boolean>>({}); // the properties whose hint is open
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (error) return <p className="empty">Could not load system properties. {error}</p>;
  if (!list) return <p className="empty">Loading…</p>;

  const groups = [...new Set(list.properties.map(groupOf))];
  const group = chosen !== null && groups.includes(chosen) ? chosen : groups[0];
  const inGroup = (g: string) => list.properties.filter((p) => groupOf(p) === g);
  const dirty = (p: PropertyRow) => p.name in drafts && drafts[p.name].trim() !== stored(p);
  const dirtyIn = (g: string) => inGroup(g).filter(dirty);

  const forget = (names: string[]) => {
    setDrafts((before) => Object.fromEntries(Object.entries(before).filter(([name]) => !names.includes(name))));
    setErrors((before) => Object.fromEntries(Object.entries(before).filter(([name]) => !names.includes(name))));
  };

  const edit = (p: PropertyRow, text: string) => {
    setDrafts((before) => ({ ...before, [p.name]: text }));
    setErrors((before) => Object.fromEntries(Object.entries(before).filter(([name]) => name !== p.name)));
  };

  const save = async (p: PropertyRow) => {
    setBusy(p.name);
    try {
      const fresh = await saveProperty(p.name, drafts[p.name] ?? stored(p));
      setList(fresh);
      forget([p.name]);
      if (p.name === SYSTEM_CURRENCY) onCurrencyChange?.(); // every amount in the app is now in this currency
      setSaved(p.name);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setSaved(null), 1600);
    } catch (e) {
      setErrors((before) => ({ ...before, [p.name]: (e as Error).message }));
    } finally {
      setBusy(null);
    }
  };

  const choose = (g: string) => {
    if (g === group) return setWanted(null);
    if (dirtyIn(group).length > 0) return setWanted(g);
    setWanted(null);
    setChosen(g);
  };

  const discard = () => {
    forget(dirtyIn(group).map((p) => p.name));
    setChosen(wanted);
    setWanted(null);
  };

  const unsaved = dirtyIn(group).length;

  return (
    <div className="sp-page">
      <div className="top">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>System properties</h1>
          <p className="sub">Settings for the whole installation. Locked settings can't be changed here.</p>
        </div>
      </div>

      <div className="sp-layout">
        <div className="sp-tabs" role="tablist" aria-orientation="vertical" aria-label="Property groups">
          {groups.map((g) => (
            <button key={g} role="tab" id={`sp-tab-${g}`} aria-selected={g === group} aria-controls="sp-panel"
              className={g === group ? "sp-tab on" : "sp-tab"} onClick={() => choose(g)}>
              <span>{title(g)}</span>
              <span className="sp-count">
                {dirtyIn(g).length > 0 && <i className="sp-dot" title="Unsaved changes" aria-label="Unsaved changes" />}
                {inGroup(g).length}
              </span>
            </button>
          ))}
        </div>

        <div id="sp-panel" role="tabpanel" aria-labelledby={`sp-tab-${group}`}>
          {wanted !== null && (
            <div className="sp-prompt" role="alert">
              <span>Discard changes to {unsaved} {unsaved === 1 ? "setting" : "settings"} in {title(group)}?</span>
              <span className="sp-prompt-actions">
                <button className="btn small" onClick={discard}>Discard</button>
                <button className="btn ghost small" onClick={() => setWanted(null)}>Keep editing</button>
              </span>
            </div>
          )}
          <div className="sp-card">
            <div className="sp-head">{title(group)}</div>
            {inGroup(group).map((p) => {
              const text = drafts[p.name] ?? stored(p);
              const edited = dirty(p);
              return (
                <div key={p.name} className={errors[p.name] ? "sp-row bad" : "sp-row"}>
                  <div className="sp-line">
                    <div>
                      <div className="sp-namerow">
                        <code className="sp-name">{p.name}</code>
                        <button className="sp-info" aria-label={`About ${p.name}`} aria-expanded={!!shown[p.name]}
                          onClick={() => setShown((before) => ({ ...before, [p.name]: !before[p.name] }))}>ⓘ</button>
                      </div>
                      <div className="sp-tags">
                        <span className="sp-tag">{p.type}</span>
                        {p.allow_null && <span className="sp-tag">Optional</span>}
                        {p.read_only && <span className="sp-tag lock">Locked</span>}
                      </div>
                    </div>
                    <div className="sp-actions">
                      {edited && <button className="btn ghost small" onClick={() => forget([p.name])}>Revert</button>}
                      {edited && <button className="btn small" disabled={busy === p.name} onClick={() => save(p)}>Save</button>}
                      {!edited && saved === p.name && <span className="sp-saved">Saved</span>}
                    </div>
                  </div>
                  {shown[p.name] && <p className="sp-hint">{p.hint}</p>}
                  {p.type === "Boolean" ? (
                    <select aria-label={p.name} value={text} disabled={p.read_only} onChange={(e) => edit(p, e.target.value)}>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : p.type === "Lookup" ? (
                    <select aria-label={p.name} value={text} disabled={p.read_only} onChange={(e) => edit(p, e.target.value)}>
                      {p.allow_null && <option value="">Not set</option>}
                      {p.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  ) : p.name === SYSTEM_CURRENCY ? (
                    <>
                      {/* The browser's own search box: it filters the catalog by code or name as you type. The server
                          checks the code against the catalog, so text that is not in the list is refused. */}
                      <input aria-label={p.name} list="sp-currencies" value={text} disabled={p.read_only} autoComplete="off" spellCheck={false}
                        placeholder="Search by code or name" onChange={(e) => edit(p, e.target.value)} />
                      <datalist id="sp-currencies">
                        {list.currencies.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                      </datalist>
                    </>
                  ) : p.name === LOCALE_DEFAULT ? (
                    <select aria-label={p.name} value={text} disabled={p.read_only} onChange={(e) => edit(p, e.target.value)}>
                      {list.locales.map((l) => <option key={l.tag} value={l.tag}>{l.label}</option>)}
                    </select>
                  ) : p.type === "Date" ? (
                    <input aria-label={p.name} type="date" value={text} disabled={p.read_only} onChange={(e) => edit(p, e.target.value)} />
                  ) : p.type === "Time" ? (
                    <input aria-label={p.name} type="time" value={text} disabled={p.read_only} onChange={(e) => edit(p, e.target.value)} />
                  ) : (
                    <input aria-label={p.name} value={text} disabled={p.read_only} placeholder={p.allow_null ? "Not set" : ""}
                      onChange={(e) => edit(p, e.target.value)} />
                  )}
                  {errors[p.name] && <p className="sp-err" role="alert">{errors[p.name]}</p>}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
