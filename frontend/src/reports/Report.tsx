import { useMemo, useRef, useState } from "react";
import type { Condition } from "../api";
import { Combobox } from "../Combobox";
import { FilterChips } from "../FilterChips";
import { flatten } from "../listFilters";
import { Link } from "../router";
import { PATHS } from "../routes";
import { ReportFilterDrawer } from "../ReportFilterDrawer";
import { useChoiceNames } from "../useChoiceNames";
import { useRequest } from "../useRequest";
import { ExpansionProvider } from "./expansion";
import { calculateReport, fetchReportChoices, fetchReportDefinition, ReportRequestError } from "./api";
import { ParameterControls, parametersFor, problems, initialValues, type Values } from "./parameters";
import type { ReportDefinition, ReportListItem, ReportResult, SectionData } from "./types";
import { VIEW_COMPONENTS } from "./viewComponents";

/** Whether a section has nothing in it. */
function isEmpty(data: SectionData): boolean {
  if ("items" in data) return data.items.length === 0;
  if ("series" in data) return data.series.every((s) => s.points.length === 0);
  if ("nodes" in data) return data.nodes.length === 0;
  return data.rows.length === 0;
}

/** The page's heading: the report's name, which is also the searchable list of reports. */
export function ReportPicker({ reports, value, onChange }: { reports: ReportListItem[]; value: string; onChange: (key: string) => void }) {
  const options = reports.map((r) => ({ id: r.key, label: r.title, detail: r.description }));
  return <h1 className="rp-title"><Combobox options={options} value={value} onChange={(id) => onChange(String(id))} label="Report" placeholder="Choose a report" /></h1>;
}

/** What went wrong with a request, in words a person can act on, by what the server said it was. */
function Failure({ error, isAdmin, onRetry }: { error: ReportRequestError; isAdmin: boolean; onRetry: () => void }) {
  if (error.code === "unavailable_data") {
    const link = error.reason === "no_system_currency" ? { to: PATHS.properties, text: "Choose it on System properties" } : { to: PATHS.currencies, text: "Add rates on Currencies" };
    return (
      <div className="panel rp-state" role="alert"><h2>The report cannot be worked out yet</h2>
        <p>{error.message}</p>
        {isAdmin ? <p><Link to={link.to}>{link.text}</Link></p> : <p>Ask an administrator.</p>}
      </div>
    );
  }
  if (error.code === "invalid_input") {
    return (
      <div className="panel rp-state" role="alert"><h2>That cannot be asked for</h2><p>{error.message}</p></div>
    );
  }
  return (
    <div className="panel rp-state" role="alert"><h2>The report could not be worked out</h2>
      <p>Something went wrong on our side, and no figures are shown. Nothing was changed.</p>
      <p><button className="link" onClick={onRetry}>Try again</button></p>
    </div>
  );
}

type Answer = { result: ReportResult } | { failure: ReportRequestError };

/** One report, opened at its defaults: its parameters, filters and the drawer live here and nowhere else, so leaving or reloading
 *  starts afresh. A parameter is checked before anything is asked, and an answer that is not for the newest question is never shown. */
function ReportBody({ definition, reports, isAdmin, onPick }: { definition: ReportDefinition; reports: ReportListItem[]; isAdmin: boolean; onPick: (key: string) => void }) {
  const [values, setValues] = useState<Values>(() => initialValues(definition));
  const [filters, setFilters] = useState<Condition[]>(() => (definition.filters.enabled ? definition.filters.defaults : []));
  const [drawer, setDrawer] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);
  const errors = problems(definition, values);
  const valid = Object.values(errors).every((e) => e === null);

  const answer = useRequest<Answer>(
    (signal) => calculateReport(definition.key, { parameters: parametersFor(definition, values), filters }, signal).then(
      (result) => ({ result }),
      (error) => { if (error instanceof ReportRequestError) return { failure: error }; throw error; }),
    [definition.key, JSON.stringify(values), JSON.stringify(filters)], { skip: !valid });

  const tree = definition.filters.enabled ? definition.filters.fields : { fields: [], relations: [] };
  const nodes = useMemo(() => new Map(flatten(tree).map((n) => [n.key, n])), [tree]);
  const { named, ensureChoices } = useChoiceNames(definition.key, (field) => fetchReportChoices(definition.key, field), filters, nodes);

  const shown = valid && !answer.error ? answer.data : null;         // nothing stale is shown under parameters that cannot be asked for, or after a request that failed
  const result = shown && "result" in shown ? shown.result : null;
  const failure = shown && "failure" in shown ? shown.failure : null;
  const header = result ? definition.sections.find((s) => s.kind === "summary") : undefined;
  const busy = answer.loading && !!shown;

  const body = () => {
    if (!valid) return <p className="empty" role="status">Fix the highlighted choice to see the report.</p>;
    if (answer.error) return <Failure error={new ReportRequestError(answer.error, "other", 0)} isAdmin={isAdmin} onRetry={answer.reload} />;
    if (failure) return <Failure error={failure} isAdmin={isAdmin} onRetry={answer.reload} />;
    if (!result) return <p className="empty" role="status">Calculating…</p>;
    // A report says it has nothing at all with the note `no_data` (its headline figures are zeros, so no section is empty); otherwise it is
    // empty when every section is.
    const noData = result.notes.find((n) => !n.section && n.code === "no_data");
    if (noData || definition.sections.every((s) => isEmpty(result.sections[s.key]))) {
      return (
        <div className="panel rp-state"><h2>Nothing to show</h2>
          <p>{noData ? noData.text : filters.length > 0 ? "Nothing matches these filters." : "There is nothing to show for these choices."}</p>
          {filters.length > 0 && <p><button className="link" onClick={() => setFilters([])}>Clear filters</button></p>}
        </div>
      );
    }
    const general = result.notes.filter((n) => !n.section);
    return (
      <div className={busy ? "rp-body rp-busy" : "rp-body"} aria-busy={busy}>
        {general.map((n) => <p className="notice info" role="status" key={n.code}>{n.text}</p>)}
        <ExpansionProvider>
        <div className="rp-grid">
          {definition.sections.filter((s) => s !== header).map((section) => {
            const View = VIEW_COMPONENTS[section.view];
            const notes = result.notes.filter((n) => n.section === section.key);
            return (
              <section className={`panel rp-card rp-span-${section.columns}`} key={section.key} aria-label={section.title}>
                <View section={section} data={result.sections[section.key]} currency={{ ...result.currency, name: result.currency.code }} />
                {notes.map((n) => <p className="rp-note" key={n.code}>{n.text}</p>)}
              </section>
            );
          })}
        </div>
        </ExpansionProvider>
      </div>
    );
  };

  const Header = header ? VIEW_COMPONENTS[header.view] : null;
  return (
    <>
      <div className="top rp-top">
        <div className="rp-head">
          <div className="eyebrow">Reports</div>
          <ReportPicker reports={reports} value={definition.key} onChange={onPick} />
          <p className="rp-desc">{definition.description}</p>
        </div>
        {Header && header && result && (
          <div className={busy ? "rp-summary rp-busy" : "rp-summary"}>
            <Header section={header} data={result.sections[header.key]} currency={{ ...result.currency, name: result.currency.code }} />
            {result.notes.filter((n) => n.section === header.key).map((n) => <p className="rp-note" key={n.code}>{n.text}</p>)}
          </div>
        )}
      </div>
      <div className="rp-bar">
        <ParameterControls definition={definition} values={values} errors={errors} onChange={(key, value) => setValues((before) => ({ ...before, [key]: value }))} />
        {definition.filters.enabled && (
          <button className="btn ghost small rp-filters" aria-haspopup="dialog" onClick={(e) => { opener.current = e.currentTarget; setDrawer(true); }}>
            Filters{filters.length > 0 ? ` (${filters.length})` : ""}</button>
        )}
      </div>
      {Object.entries(errors).filter(([, e]) => e).map(([key, e]) => <p className="rp-error" role="alert" key={key}>{e}</p>)}
      <FilterChips conditions={filters} nodes={nodes} names={named} onRemove={(i) => setFilters(filters.filter((_, j) => j !== i))} onClear={() => setFilters([])} />
      {body()}
      {drawer && definition.filters.enabled && (
        <ReportFilterDrawer title={definition.title} tree={tree} applied={filters} choices={named} ensureChoices={ensureChoices}
          onApply={(conditions) => { setFilters(conditions); setDrawer(false); opener.current?.focus(); }}
          onClose={() => { setDrawer(false); opener.current?.focus(); }} />
      )}
    </>
  );
}

/** The report with this key: its definition, then the page. Another key is another report, opened afresh. */
export function Report({ item, reports, isAdmin, onPick }: { item: ReportListItem; reports: ReportListItem[]; isAdmin: boolean; onPick: (key: string) => void }) {
  const definition = useRequest((signal) => fetchReportDefinition(item.key, signal), [item.key], { reset: true });
  if (definition.error) {
    return (
      <>
        <div className="top rp-top"><div className="rp-head"><div className="eyebrow">Reports</div><ReportPicker reports={reports} value={item.key} onChange={onPick} /></div></div>
        <div className="empty" role="alert"><p>Could not load this report. {definition.error}</p><p><button className="link" onClick={definition.reload}>Try again</button></p></div>
      </>
    );
  }
  if (!definition.data) {
    return (
      <>
        <div className="top rp-top"><div className="rp-head"><div className="eyebrow">Reports</div><ReportPicker reports={reports} value={item.key} onChange={onPick} /></div></div>
        <p className="empty" role="status">Loading…</p>
      </>
    );
  }
  return <ReportBody key={definition.data.key + definition.data.today} definition={definition.data} reports={reports} isAdmin={isAdmin} onPick={onPick} />;
}
