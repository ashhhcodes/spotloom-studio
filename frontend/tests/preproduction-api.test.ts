import assert from "node:assert/strict";
import test from "node:test";
import { initialNorthstarBrief } from "../src/app/projects/sample-northstar/creative-brief";
import {
  isPreproductionResponse,
  PreproductionApiError,
  requestPreproductionEvaluation,
  toPreproductionRequest,
} from "../src/app/projects/sample-northstar/creative/preproduction-api";
import { northstarDemoProject } from "../src/app/projects/sample-northstar/review/demo-facts";
import { cloneInitialStoryboard } from "../src/app/projects/sample-northstar/storyboard-model";

const facts = northstarDemoProject.facts;
const brief = { ...initialNorthstarBrief, reliedUponFactIds: [...initialNorthstarBrief.reliedUponFactIds] };
const scenes = cloneInitialStoryboard();

function validResponse() {
  return {
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

test("request mapping sends only current facts, brief, and ordered scenes", () => {
  const request = toPreproductionRequest(facts, brief, scenes);
  assert.deepEqual(Object.keys(request), ["facts", "brief", "storyboard"]);
  assert.deepEqual(Object.keys(request.facts), ["facts"]);
  assert.deepEqual(request.facts.facts, facts);
  assert.deepEqual(request.brief, brief);
  assert.deepEqual(request.storyboard.scenes, scenes);
  assert.equal(request.facts.facts[1].status, "approved");
  assert.equal(request.facts.facts[1].source.kind, "illustrative-placeholder");
  assert.equal("readiness" in request, false);
  assert.equal("runtime" in request, false);
});

test("successful response is accepted only when contract fields and derived counts agree", async () => {
  const payload = validResponse();
  assert.equal(isPreproductionResponse(payload), true);
  const result = await requestPreproductionEvaluation(
    toPreproductionRequest(facts, brief, scenes),
    async () => new Response(JSON.stringify(payload), { status: 200 }),
  );
  assert.equal(result.factualVerification, "not-performed");
  assert.equal(result.summary.blockerCount, 1);
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
  assert.equal(isPreproductionResponse(payload), false);
});
