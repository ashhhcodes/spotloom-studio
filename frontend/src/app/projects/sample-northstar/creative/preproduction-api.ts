import type { CreativeBrief } from "../creative-brief";
import type { StoryboardScene } from "../storyboard-model";
import type { ProjectFact } from "../review/demo-facts";

export type PreproductionRequest = {
  facts: { facts: ProjectFact[] };
  brief: CreativeBrief;
  storyboard: { scenes: StoryboardScene[] };
};

export type BackendFinding = {
  id: string;
  severity: "blocker" | "warning" | "info";
  category: "brief" | "facts" | "storyboard" | "runtime" | "grounding" | "production";
  title: string;
  explanation: string;
  resolution: string;
  destinationRoutes: string[];
  blocksReadiness: boolean;
  affectedFactId: string | null;
  affectedSceneId: string | null;
};

export type PreproductionResponse = {
  requestSchemaValid: true;
  evaluationStatus: "evaluated-with-limitations";
  readinessStatus: "needs-attention" | "ready-for-human-review";
  briefConfirmationSignal: "caller-declared-confirmed" | "not-confirmed";
  factualVerification: "not-performed";
  findings: BackendFinding[];
  summary: { blockerCount: number; warningCount: number; infoCount: number };
  factSummary: {
    total: number;
    callerMarkedApproved: number;
    unreviewed: number;
    rejected: number;
    invalidStatus: number;
    eligibleFactIds: string[];
  };
  storyboardSummary: {
    sceneCount: number;
    plannedRuntimeSeconds: number | null;
    targetRuntimeSeconds: number;
    runtimeDifferenceSeconds: number | null;
    runtimeUnavailableReason: "empty" | null;
  };
};

export type SafeValidationIssue = { path: string; message: string };
export type PreproductionApiErrorKind = "unavailable" | "http" | "invalid-request" | "invalid-response";

export class PreproductionApiError extends Error {
  constructor(
    readonly kind: PreproductionApiErrorKind,
    message: string,
    readonly status?: number,
    readonly issues: SafeValidationIssue[] = [],
  ) {
    super(message);
    this.name = "PreproductionApiError";
  }
}

const evaluationEndpoint = "/api/adforge/validate/preproduction";
const workspaceRoutes = new Set([
  "/projects/sample-northstar/brief",
  "/projects/sample-northstar/review",
  "/projects/sample-northstar/storyboard",
  "/projects/sample-northstar/creative",
]);
const severities = new Set(["blocker", "warning", "info"]);
const categories = new Set(["brief", "facts", "storyboard", "runtime", "grounding", "production"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNullableCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isFinding(value: unknown): value is BackendFinding {
  if (!isRecord(value) || !hasExactKeys(value, [
    "id", "severity", "category", "title", "explanation", "resolution", "destinationRoutes",
    "blocksReadiness", "affectedFactId", "affectedSceneId",
  ])) return false;
  return typeof value.id === "string"
    && severities.has(String(value.severity))
    && categories.has(String(value.category))
    && typeof value.title === "string"
    && typeof value.explanation === "string"
    && typeof value.resolution === "string"
    && Array.isArray(value.destinationRoutes)
    && value.destinationRoutes.every((route) => typeof route === "string" && workspaceRoutes.has(route))
    && typeof value.blocksReadiness === "boolean"
    && (typeof value.affectedFactId === "string" || value.affectedFactId === null)
    && (typeof value.affectedSceneId === "string" || value.affectedSceneId === null);
}

/** Runtime-check the strict backend response before treating it as an evaluation. */
export function isPreproductionResponse(value: unknown): value is PreproductionResponse {
  if (!isRecord(value) || !hasExactKeys(value, [
    "requestSchemaValid", "evaluationStatus", "readinessStatus", "briefConfirmationSignal",
    "factualVerification", "findings", "summary", "factSummary", "storyboardSummary",
  ]) || value.requestSchemaValid !== true
    || value.evaluationStatus !== "evaluated-with-limitations"
    || (value.readinessStatus !== "needs-attention" && value.readinessStatus !== "ready-for-human-review")
    || (value.briefConfirmationSignal !== "caller-declared-confirmed" && value.briefConfirmationSignal !== "not-confirmed")
    || value.factualVerification !== "not-performed"
    || !Array.isArray(value.findings) || !value.findings.every(isFinding)
    || !isRecord(value.summary) || !hasExactKeys(value.summary, ["blockerCount", "warningCount", "infoCount"])
    || !isCount(value.summary.blockerCount)
    || !isCount(value.summary.warningCount) || !isCount(value.summary.infoCount)
    || !isRecord(value.factSummary) || !hasExactKeys(value.factSummary, [
      "total", "callerMarkedApproved", "unreviewed", "rejected", "invalidStatus", "eligibleFactIds",
    ]) || !isCount(value.factSummary.total)
    || !isCount(value.factSummary.callerMarkedApproved) || !isCount(value.factSummary.unreviewed)
    || !isCount(value.factSummary.rejected) || !isCount(value.factSummary.invalidStatus)
    || !isStringList(value.factSummary.eligibleFactIds)
    || !isRecord(value.storyboardSummary) || !hasExactKeys(value.storyboardSummary, [
      "sceneCount", "plannedRuntimeSeconds", "targetRuntimeSeconds", "runtimeDifferenceSeconds", "runtimeUnavailableReason",
    ]) || !isCount(value.storyboardSummary.sceneCount)
    || !isNullableCount(value.storyboardSummary.plannedRuntimeSeconds)
    || !isCount(value.storyboardSummary.targetRuntimeSeconds)
    || !isNullableCount(value.storyboardSummary.runtimeDifferenceSeconds)
    || (value.storyboardSummary.runtimeUnavailableReason !== null
      && value.storyboardSummary.runtimeUnavailableReason !== "empty")) {
    return false;
  }

  const response = value as unknown as PreproductionResponse;
  const blockerCount = response.findings.filter((finding) => finding.blocksReadiness).length;
  const warningCount = response.findings.filter((finding) => finding.severity === "warning").length;
  const infoCount = response.findings.filter((finding) => finding.severity === "info").length;
  const counts = response.factSummary;
  const runtime = response.storyboardSummary;
  return response.summary.blockerCount === blockerCount
    && response.summary.warningCount === warningCount
    && response.summary.infoCount === infoCount
    && response.readinessStatus === (blockerCount > 0 ? "needs-attention" : "ready-for-human-review")
    && counts.total === counts.callerMarkedApproved + counts.unreviewed + counts.rejected
    && counts.invalidStatus === 0
    && counts.eligibleFactIds.length === counts.callerMarkedApproved
    && [15, 30, 60].includes(runtime.targetRuntimeSeconds)
    && (runtime.sceneCount === 0
      ? runtime.plannedRuntimeSeconds === null && runtime.runtimeUnavailableReason === "empty"
        && runtime.runtimeDifferenceSeconds === null
      : runtime.plannedRuntimeSeconds !== null && runtime.runtimeUnavailableReason === null
        && runtime.runtimeDifferenceSeconds === runtime.plannedRuntimeSeconds - runtime.targetRuntimeSeconds);
}

/** Copy only the API's three documented inputs; derived client metrics are never sent. */
export function toPreproductionRequest(
  facts: readonly ProjectFact[],
  brief: CreativeBrief,
  scenes: readonly StoryboardScene[],
): PreproductionRequest {
  return {
    facts: { facts: facts.map((fact) => ({ ...fact, revisions: [...fact.revisions], source: { ...fact.source } })) },
    brief: { ...brief, reliedUponFactIds: [...brief.reliedUponFactIds] },
    storyboard: { scenes: scenes.map((scene) => ({ ...scene })) },
  };
}

function safeIssues(value: unknown): SafeValidationIssue[] {
  if (!isRecord(value) || !Array.isArray(value.issues)) return [];
  return value.issues.flatMap((issue): SafeValidationIssue[] => {
    if (!isRecord(issue) || typeof issue.path !== "string" || typeof issue.message !== "string") return [];
    const path = issue.path.slice(0, 180);
    if (!/^[a-zA-Z0-9_.\[\]-]+$/.test(path)) return [];
    return [{ path, message: "Value does not match the supported contract." }];
  }).slice(0, 8);
}

export async function requestPreproductionEvaluation(
  request: PreproductionRequest,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<PreproductionResponse> {
  let response: Response;
  try {
    response = await fetcher(evaluationEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new PreproductionApiError("unavailable", "The local validation backend is unavailable. Start it and retry.");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    if (response.ok) {
      throw new PreproductionApiError("invalid-response", "The backend returned an unreadable response.", response.status);
    }
    body = null;
  }

  if (!response.ok) {
    if (response.status === 422) {
      throw new PreproductionApiError(
        "invalid-request",
        "The backend rejected fields outside its supported input contract.",
        response.status,
        safeIssues(body),
      );
    }
    throw new PreproductionApiError("http", `The backend returned HTTP ${response.status}. Retry the evaluation.`, response.status);
  }

  if (!isPreproductionResponse(body)) {
    throw new PreproductionApiError("invalid-response", "The backend response did not match the supported evaluation contract.", response.status);
  }
  return body;
}
