import { type Choices, type Condition, signIn } from "../api";
import type { ReportDefinition, ReportListItem, ReportResult } from "./types";

/** A report request the server refused or could not answer, with what the page needs to say so. `code` is the server's stable answer
 *  (`invalid_input` with the `path` to what was wrong, `unavailable_data` with a `reason`, `calculation_error`); "other" is anything
 *  else (not a report answer: a gateway, say). `message` is written to be shown. */
export class ReportRequestError extends Error {
  code: "invalid_input" | "unavailable_data" | "calculation_error" | "other";
  status: number;
  path: (string | number)[];
  reason: string | null;
  missingRates: string[];
  constructor(message: string, code: ReportRequestError["code"], status: number, path: (string | number)[] = [], reason: string | null = null, missingRates: string[] = []) {
    super(message);
    this.code = code;
    this.status = status;
    this.path = path;
    this.reason = reason;
    this.missingRates = missingRates;
  }
}

const CODES = ["invalid_input", "unavailable_data", "calculation_error"] as const;

async function call<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method, signal,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (response.status === 401) {
    signIn();                                          // the session ended: sign in again
    throw new Error("You are signed out.");
  }
  if (!response.ok) {
    const answer = await response.json().catch(() => null);
    const code = CODES.find((c) => c === answer?.code) ?? "other";
    throw new ReportRequestError(
      typeof answer?.detail === "string" ? answer.detail : `The server answered ${response.status}`, code, response.status,
      Array.isArray(answer?.path) ? answer.path : [], typeof answer?.reason === "string" ? answer.reason : null,
      Array.isArray(answer?.missing_rates) ? answer.missing_rates.map(String) : []);
  }
  return response.json();
}

/** The reports this person may see, by title. */
export async function fetchReports(signal?: AbortSignal): Promise<ReportListItem[]> {
  return (await call<{ reports: ReportListItem[] }>("GET", "/api/reports", undefined, signal)).reports;
}

/** One report's public metadata: its parameters with the defaults resolved by the server, its sections and what it can be filtered by. */
export function fetchReportDefinition(key: string, signal?: AbortSignal): Promise<ReportDefinition> {
  return call("GET", `/api/reports/${encodeURIComponent(key)}`, undefined, signal);
}

/** The report for these parameters and filters. Every parameter is named: the server fills in none. The filters are sent as they
 *  are (an empty list means none, and leaving them out would mean the report's own). */
export function calculateReport(key: string, request: { parameters: Record<string, string | number>; filters: Condition[] }, signal?: AbortSignal): Promise<ReportResult> {
  return call("POST", `/api/reports/${encodeURIComponent(key)}`, request, signal);
}

/** What to pick from when filtering a report by a record (an account type): drawn from what the person may see. */
export function fetchReportChoices(key: string, field: string, signal?: AbortSignal): Promise<Choices> {
  return call("GET", `/api/reports/${encodeURIComponent(key)}/choices/${field.split(".").map(encodeURIComponent).join(".")}`, undefined, signal);
}
