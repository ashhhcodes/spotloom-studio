import assert from "node:assert/strict";
import test from "node:test";
import { initialNorthstarBrief } from "../src/app/projects/sample-northstar/creative-brief.ts";
import {
  isPreproductionResponse,
  PreproductionApiError,
  requestPreproductionEvaluation,
  toPreproductionRequest,
  type PreproductionResponse,
} from "../src/app/projects/sample-northstar/creative/preproduction-api.ts";
import { northstarDemoProject } from "../src/app/projects/sample-northstar/review/demo-facts.ts";
import { cloneInitialStoryboard } from "../src/app/projects/sample-northstar/storyboard-model.ts";

const facts = northstarDemoProject.facts;
const brief = { ...initialNorthstarBrief, reliedUponFactIds: [...initialNorthstarBrief.reliedUponFactIds] };
const scenes = cloneInitialStoryboard();
const snapshot = toPreproductionRequest(facts, brief, scenes);
const request = { ...snapshot, correlationId: "a714886a-bd4c-4dde-9f88-8e29c5d764b1" };

function validResponse(): PreproductionResponse {
  return {
    correlationId: request.correlationId,
    requestSchemaValid: true,
    evaluationStatus: "evaluated-with-limitations",
    readinessStatus: "needs-attention",
    briefConfirmationSignal: "not-confirmed",
    factualVerification: "not-performed",
    findings: [{
      id: "brief.confirmation.required",
      severity: "blocker",
      category: "brief",
      title: "Confirm the brief",
      explanation: "The caller did not declare confirmation.",
      resolution: "Review the brief.",
      destinationRoutes: ["/projects/sample-northstar/brief"],
      blocksReadiness: true,
      affectedFactId: null,
      affectedSceneId: null,
    }],
    summary: { blockerCount: 1, warningCount: 0, infoCount: 0 },
    factSummary: {
      total: 3,
      callerMarkedApproved: 1,
      unreviewed: 1,
      rejected: 1,
      invalidStatus: 0,
      eligibleFactIds: ["audience"],
    },
    storyboardSummary: {
      sceneCount: scenes.length,
      plannedRuntimeSeconds: scenes.reduce((total, scene) => total + scene.durationSeconds, 0),
      targetRuntimeSeconds: 15,
      runtimeDifferenceSeconds: scenes.reduce((total, scene) => total + scene.durationSeconds, 0) - 15,
      runtimeUnavailableReason: null,
    },
  };
}

function responseForRequest(payload: PreproductionResponse, status = 200): typeof fetch {
  return async (_input, init) => {
    const submitted = JSON.parse(String(init?.body)) as { correlationId: string };
    return new Response(JSON.stringify({ ...payload, correlationId: submitted.correlationId }), { status });
  };
}

test("request mapping sends only current facts, brief, and ordered scenes", () => {
  const request = toPreproductionRequest(facts, brief, scenes);
  assert.deepEqual(Object.keys(request), ["facts", "brief", "storyboard"]);
  assert.deepEqual(Object.keys(request.facts), ["facts"]);
  assert.deepEqual(request.facts.facts, facts);
  assert.deepEqual(request.brief, brief);
  assert.deepEqual(request.storyboard.scenes, scenes.map((scene) => ({
    id: scene.id,
    title: scene.title,
    narrativePurpose: scene.narrativePurpose,
    visualDirection: scene.visualDirection,
    onScreenText: scene.onScreenText,
    narration: scene.narration,
    durationSeconds: scene.durationSeconds,
    transitionNote: scene.transitionNote,
  })));
  assert.deepEqual(Object.keys(request.storyboard.scenes[0] ?? {}).sort(), [
    "durationSeconds", "id", "narration", "narrativePurpose", "onScreenText", "title", "transitionNote", "visualDirection",
  ]);
  assert.equal("role" in (request.storyboard.scenes[0] ?? {}), false);
  assert.equal("transition" in (request.storyboard.scenes[0] ?? {}), false);
  assert.equal(request.facts.facts[1].status, "approved");
  assert.equal(request.facts.facts[1].source.kind, "illustrative-placeholder");
  assert.equal("readiness" in request, false);
  assert.equal("runtime" in request, false);
});

test("the HTTP request serializes exactly the mapped contract to the scoped same-origin path", async () => {
  let requestedUrl: RequestInfo | URL | undefined;
  let requestedInit: RequestInit | undefined;
  const request = toPreproductionRequest(facts, brief, scenes);
  await requestPreproductionEvaluation(request, async (input, init) => {
    requestedUrl = input;
    requestedInit = init;
    const sent = JSON.parse(String(init?.body)) as { correlationId: string };
    return new Response(JSON.stringify({ ...validResponse(), correlationId: sent.correlationId }), { status: 200 });
  });

  assert.equal(requestedUrl, "/api/adforge/validate/preproduction");
  assert.equal(requestedInit?.method, "POST");
  assert.equal(new Headers(requestedInit?.headers).get("content-type"), "application/json");
  const sent = JSON.parse(String(requestedInit?.body));
  assert.match(sent.correlationId, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  const sentSnapshot = { ...sent };
  delete sentSnapshot.correlationId;
  assert.deepEqual(sentSnapshot, request);
  assert.equal(requestedInit?.cache, "no-store");
});

test("successful response is accepted only when contract fields and derived counts agree", async () => {
  const payload = validResponse();
  assert.equal(isPreproductionResponse(payload, request), true);
  const result = await requestPreproductionEvaluation(
    request,
    responseForRequest(payload),
  );
  assert.equal(result.factualVerification, "not-performed");
  assert.equal(result.summary.blockerCount, 1);
});

test("responses require a valid correlation ID matching the current evaluation", async () => {
  const otherId = "d7ad5c24-4bb0-44da-87cb-3c73fffe87a8";
  const otherRequest = { ...request, correlationId: otherId };
  const missing = { ...validResponse() } as Partial<PreproductionResponse>;
  delete missing.correlationId;
  const malformed = { ...validResponse(), correlationId: "not-a-uuid" };
  const responseFromOtherEvaluation = { ...validResponse(), correlationId: otherId };

  assert.equal(isPreproductionResponse(missing, request), false);
  assert.equal(isPreproductionResponse(malformed, request), false);
  assert.equal(isPreproductionResponse(responseFromOtherEvaluation, request), false);
  assert.equal(isPreproductionResponse(responseFromOtherEvaluation, otherRequest), true);

  for (const payload of [missing, malformed, responseFromOtherEvaluation]) {
    await assert.rejects(
      requestPreproductionEvaluation(request, async () => new Response(JSON.stringify(payload))),
      (error: unknown) => error instanceof PreproductionApiError
        && error.kind === "invalid-response"
        && !error.message.includes("not-a-uuid")
        && !error.message.includes(otherId),
    );
  }
});

test("empty storyboard response matches the request with unavailable runtime", async () => {
  const emptySnapshot = toPreproductionRequest(facts, brief, []);
  const emptyRequest = { ...emptySnapshot, correlationId: request.correlationId };
  const payload = validResponse();
  payload.correlationId = emptyRequest.correlationId;
  payload.storyboardSummary = {
    sceneCount: 0,
    plannedRuntimeSeconds: null,
    targetRuntimeSeconds: brief.duration,
    runtimeDifferenceSeconds: null,
    runtimeUnavailableReason: "empty",
  };
  assert.equal(isPreproductionResponse(payload, emptyRequest), true);
  const result = await requestPreproductionEvaluation(emptySnapshot, responseForRequest(payload));
  assert.equal(result.storyboardSummary.plannedRuntimeSeconds, null);
  assert.equal(result.storyboardSummary.runtimeUnavailableReason, "empty");
});

test("internally consistent results that disagree with the submitted snapshot are rejected safely", async () => {
  const mutations = [
    (payload: ReturnType<typeof validResponse>) => {
      payload.factSummary.total += 1;
      payload.factSummary.unreviewed += 1;
    },
    (payload: ReturnType<typeof validResponse>) => {
      payload.factSummary.callerMarkedApproved += 1;
      payload.factSummary.unreviewed -= 1;
    },
    (payload: ReturnType<typeof validResponse>) => {
      payload.factSummary.rejected -= 1;
      payload.factSummary.unreviewed += 1;
    },
    (payload: ReturnType<typeof validResponse>) => { payload.factSummary.eligibleFactIds = ["product"]; },
    (payload: ReturnType<typeof validResponse>) => { payload.briefConfirmationSignal = "caller-declared-confirmed"; },
    (payload: ReturnType<typeof validResponse>) => {
      payload.storyboardSummary.sceneCount += 1;
      payload.storyboardSummary.plannedRuntimeSeconds! += 1;
      payload.storyboardSummary.runtimeDifferenceSeconds! += 1;
    },
    (payload: ReturnType<typeof validResponse>) => {
      payload.storyboardSummary.targetRuntimeSeconds = 30;
      payload.storyboardSummary.runtimeDifferenceSeconds = payload.storyboardSummary.plannedRuntimeSeconds! - 30;
    },
    (payload: ReturnType<typeof validResponse>) => {
      payload.storyboardSummary.plannedRuntimeSeconds! += 1;
      payload.storyboardSummary.runtimeDifferenceSeconds! += 1;
    },
  ];

  for (const mutate of mutations) {
    const payload = validResponse();
    mutate(payload);
    assert.equal(isPreproductionResponse(payload, request), false);
    await assert.rejects(
      requestPreproductionEvaluation(request, responseForRequest(payload)),
      (error: unknown) => error instanceof PreproductionApiError
        && error.kind === "invalid-response"
        && error.message.includes("submitted snapshot")
        && !error.message.includes("secret")
        && !error.message.includes("<html>"),
    );
  }
});

test("eligible fact IDs retain the submitted fact order", () => {
  const approvedSnapshot = toPreproductionRequest(
    facts.map((fact) => ({ ...fact, status: "approved" as const })),
    brief,
    scenes,
  );
  const approvedRequest = { ...approvedSnapshot, correlationId: request.correlationId };
  const payload = validResponse();
  payload.correlationId = approvedRequest.correlationId;
  payload.factSummary = {
    total: facts.length,
    callerMarkedApproved: facts.length,
    unreviewed: 0,
    rejected: 0,
    invalidStatus: 0,
    eligibleFactIds: approvedRequest.facts.facts.map((fact) => fact.id),
  };
  assert.equal(isPreproductionResponse(payload, approvedRequest), true);
  payload.factSummary.eligibleFactIds.reverse();
  assert.equal(isPreproductionResponse(payload, approvedRequest), false);
});

test("a snapshot mismatch can be retried successfully", async () => {
  let attempts = 0;
  const fetcher: typeof fetch = async (_input, init) => {
    attempts += 1;
    const payload = validResponse();
    if (attempts === 1) payload.storyboardSummary.sceneCount += 1;
    const sent = JSON.parse(String(init?.body)) as { correlationId: string };
    return new Response(JSON.stringify({ ...payload, correlationId: sent.correlationId }));
  };
  await assert.rejects(requestPreproductionEvaluation(request, fetcher), (error: unknown) =>
    error instanceof PreproductionApiError && error.kind === "invalid-response");
  const result = await requestPreproductionEvaluation(request, fetcher);
  assert.equal(attempts, 2);
  assert.equal(result.storyboardSummary.sceneCount, scenes.length);
});

test("backend unavailable produces a retryable safe error", async () => {
  await assert.rejects(
    requestPreproductionEvaluation(toPreproductionRequest(facts, brief, scenes), async () => {
      throw new TypeError("private connection detail");
    }),
    (error: unknown) => error instanceof PreproductionApiError
      && error.kind === "unavailable"
      && !error.message.includes("private connection detail"),
  );
});

test("an abort remains an abort instead of being converted to a network failure", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    requestPreproductionEvaluation(toPreproductionRequest(facts, brief, scenes), async () => {
      throw new DOMException("cancelled", "AbortError");
    }, controller.signal),
    (error: unknown) => error instanceof Error && error.name === "AbortError",
  );
});

test("a failed request can be retried successfully without rebuilding the client", async () => {
  let attempts = 0;
  const correlationIds: string[] = [];
  const fetcher: typeof fetch = async (_input, init) => {
    attempts += 1;
    const sent = JSON.parse(String(init?.body)) as { correlationId: string };
    correlationIds.push(sent.correlationId);
    if (attempts === 1) return new Response("<internal failure>", { status: 503 });
    return new Response(JSON.stringify({ ...validResponse(), correlationId: sent.correlationId }), { status: 200 });
  };
  await assert.rejects(requestPreproductionEvaluation(request, fetcher), (error: unknown) =>
    error instanceof PreproductionApiError && error.kind === "http" && !error.message.includes("internal failure"));
  const retried = await requestPreproductionEvaluation(request, fetcher);
  assert.equal(attempts, 2);
  assert.notEqual(correlationIds[0], correlationIds[1]);
  assert.equal(retried.evaluationStatus, "evaluated-with-limitations");
});

test("each evaluation retry gets a fresh ID and rejects the previous attempt response", async () => {
  let attempts = 0;
  const correlationIds: string[] = [];
  const oldId = "d7ad5c24-4bb0-44da-87cb-3c73fffe87a8";
  const fetcher: typeof fetch = async (_input, init) => {
    attempts += 1;
    const sent = JSON.parse(String(init?.body)) as { correlationId: string };
    correlationIds.push(sent.correlationId);
    const payload = validResponse();
    payload.correlationId = attempts === 1 ? oldId : sent.correlationId;
    return new Response(JSON.stringify(payload));
  };

  await assert.rejects(requestPreproductionEvaluation(request, fetcher), (error: unknown) =>
    error instanceof PreproductionApiError && error.kind === "invalid-response");
  const result = await requestPreproductionEvaluation(request, fetcher);
  assert.equal(attempts, 2);
  assert.notEqual(correlationIds[0], correlationIds[1]);
  assert.equal(result.correlationId, correlationIds[1]);
});

test("HTTP and schema errors never expose server details and keep only sanitized field paths", async () => {
  await assert.rejects(
    requestPreproductionEvaluation(toPreproductionRequest(facts, brief, scenes), async () => new Response(
      JSON.stringify({ detail: "secret stack trace" }), { status: 500 },
    )),
    (error: unknown) => error instanceof PreproductionApiError
      && error.kind === "http"
      && error.status === 500
      && !error.message.includes("secret stack trace"),
  );

  await assert.rejects(
    requestPreproductionEvaluation(toPreproductionRequest(facts, brief, scenes), async () => new Response(
      JSON.stringify({ issues: [{ path: "brief.targetAudience", message: "untrusted response text" }] }),
      { status: 422 },
    )),
    (error: unknown) => error instanceof PreproductionApiError
      && error.kind === "invalid-request"
      && error.issues[0]?.path === "brief.targetAudience"
      && error.issues[0]?.message === "Value does not match the supported contract.",
  );
});

test("invalid JSON and malformed 200 responses are not treated as successful evaluations", async () => {
  for (const response of [new Response("not json"), new Response("{}")]) {
    await assert.rejects(
      requestPreproductionEvaluation(toPreproductionRequest(facts, brief, scenes), async () => response),
      (error: unknown) => error instanceof PreproductionApiError && error.kind === "invalid-response",
    );
  }
});

test("malformed backend counts are rejected", () => {
  const payload = validResponse();
  payload.summary.blockerCount = 0;
  assert.equal(isPreproductionResponse(payload, request), false);
});

test("invalid and inconsistent response shapes or status combinations fail safely", () => {
  const baseline = validResponse();
  const mutations: unknown[] = [
    null,
    [],
    {},
    { ...baseline, unexpected: true },
    { ...baseline, readinessStatus: "ready-for-human-review" },
    { ...baseline, factSummary: { ...baseline.factSummary, total: 4 } },
    { ...baseline, factSummary: { ...baseline.factSummary, invalidStatus: 1 } },
    { ...baseline, storyboardSummary: {
      ...baseline.storyboardSummary,
      runtimeDifferenceSeconds: (baseline.storyboardSummary.runtimeDifferenceSeconds ?? 0) + 1,
    } },
    { ...baseline, findings: [{ ...baseline.findings[0], destinationRoutes: ["https://example.com"] }] },
    { ...baseline, findings: [{ ...baseline.findings[0], unexpected: "field" }] },
  ];

  for (const mutation of mutations) assert.doesNotThrow(() => assert.equal(isPreproductionResponse(mutation, request), false));
});
