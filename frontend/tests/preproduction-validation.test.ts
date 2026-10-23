import assert from "node:assert/strict";
import test from "node:test";
import {
  correctDemoFact,
  decideDemoFact,
  northstarDemoProject,
  type ProjectFact,
} from "../src/app/projects/sample-northstar/review/demo-facts";
import { initialNorthstarBrief, type CreativeBrief } from "../src/app/projects/sample-northstar/creative-brief";
import {
  appendStoryboardScene,
  cloneInitialStoryboard,
  deleteStoryboardScene,
  moveStoryboardScene,
  type StoryboardScene,
} from "../src/app/projects/sample-northstar/storyboard-model";
import { validateNorthstarPreproduction, type FindingSeverity } from "../src/app/projects/sample-northstar/preproduction-validation";

const severityOrder: Record<FindingSeverity, number> = { blocker: 0, warning: 1, info: 2 };

function makeFacts(): ProjectFact[] {
  return northstarDemoProject.facts.map((fact) => ({
    ...fact,
    revisions: [...fact.revisions],
    source: { ...fact.source },
  }));
}

function makeBrief(patch: Partial<CreativeBrief> = {}): CreativeBrief {
  return {
    ...initialNorthstarBrief,
    reliedUponFactIds: [...initialNorthstarBrief.reliedUponFactIds],
    requirementsConfirmed: true,
    ...patch,
  };
}

function findById(findings: ReturnType<typeof validateNorthstarPreproduction>["findings"], id: string) {
  return findings.find((finding) => finding.id === id);
}

test("complete confirmed demo brief has structural readiness and remains demo-only", () => {
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), cloneInitialStoryboard());
  assert.equal(result.status, "ready-for-human-review");
  assert.equal(result.projectBoundary, "demo-only");
  assert.equal(result.blockerCount, 0);
  assert.equal(result.factSummary.total, 3);
  assert.equal(result.factSummary.approved, 1);
  assert.equal(result.factSummary.unreviewed, 1);
  assert.equal(result.factSummary.rejected, 1);
  assert.equal(result.factSummary.eligibleFacts.length, 1);
  assert.ok(result.findings.some((finding) => finding.id === "production.demo-only-boundary"));
});

test("unconfirmed illustrative defaults block human-review readiness", () => {
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief({ requirementsConfirmed: false }), cloneInitialStoryboard());
  assert.equal(result.status, "needs-attention");
  assert.ok(findById(result.findings, "brief.confirmation.required"));
  assert.ok(findById(result.findings, "brief.demo-defaults"));
});

test("missing whitespace-only required brief text is identified by field", () => {
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief({ targetAudience: " \t " }), cloneInitialStoryboard());
  const finding = findById(result.findings, "brief.required.targetAudience");
  assert.equal(finding?.severity, "blocker");
  assert.equal(finding?.destinationRoutes[0], "/projects/sample-northstar/brief");
  assert.equal(findById(result.findings, "brief.required.valueProposition"), undefined);
  assert.ok(findById(validateNorthstarPreproduction(makeFacts(), makeBrief({ callToAction: "  " }), cloneInitialStoryboard()).findings, "brief.required.callToAction"));
});

test("unsupported selection values are rejected at runtime", () => {
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief({ objective: "viral" as CreativeBrief["objective"], duration: 20 as CreativeBrief["duration"] }), cloneInitialStoryboard());
  assert.ok(findById(result.findings, "brief.selection.objective"));
  assert.ok(findById(result.findings, "brief.selection.duration"));
  assert.equal(result.storyboardSummary.targetRuntimeSeconds, null);
  assert.equal(result.storyboardSummary.runtimeUnavailableReason, "invalid-target");
});

test("fact totals and eligibility use current review state and shared transitions", () => {
  const facts = makeFacts();
  facts[0] = decideDemoFact(facts[0], "approved");
  assert.equal(validateNorthstarPreproduction(facts, makeBrief(), cloneInitialStoryboard()).factSummary.eligibleFacts.length, 2);
  facts[0] = correctDemoFact(facts[0], "Fresh corrected demo wording");
  const result = validateNorthstarPreproduction(facts, makeBrief(), cloneInitialStoryboard());
  assert.equal(facts[0].status, "unreviewed");
  assert.deepEqual(facts[0].revisions, ["Small-batch roasted coffee"]);
  assert.equal(result.factSummary.unreviewed, 1);
  assert.equal(result.factSummary.approved, 1);
  assert.equal(result.factSummary.eligibleFacts.some((fact) => fact.id === "product"), false);
  assert.ok(findById(result.findings, "facts.unreviewed.product"));
});

test("approving all demo facts updates readiness without clearing brief or storyboard blockers", () => {
  const facts = makeFacts();
  facts[0] = decideDemoFact(facts[0], "approved");
  facts[2] = correctDemoFact(facts[2], "A revised illustrative message");
  facts[2] = decideDemoFact(facts[2], "approved");
  const scenes = cloneInitialStoryboard();
  scenes[0] = { ...scenes[0], onScreenText: facts[0].claim };
  scenes[1] = { ...scenes[1], narration: facts[2].claim, durationSeconds: 2.5 };

  const result = validateNorthstarPreproduction(facts, makeBrief({ requirementsConfirmed: false }), scenes);

  assert.equal(result.factSummary.approved, 3);
  assert.equal(result.factSummary.unreviewed, 0);
  assert.equal(result.factSummary.rejected, 0);
  assert.deepEqual(result.factSummary.eligibleFacts.map((fact) => fact.id), ["product", "audience", "message"]);
  assert.equal(findById(result.findings, "facts.unreviewed.product"), undefined);
  assert.equal(findById(result.findings, "facts.rejected.message"), undefined);
  assert.equal(findById(result.findings, `grounding.exact-match.${scenes[0].id}.product`)?.severity, "info");
  assert.ok(findById(result.findings, "brief.confirmation.required"));
  assert.ok(findById(result.findings, `storyboard.duration-invalid.${scenes[1].id}`));
  assert.equal(result.storyboardSummary.plannedRuntimeSeconds, null);
  assert.equal(result.storyboardSummary.runtimeUnavailableReason, "invalid-scene-duration");
  assert.equal(result.status, "needs-attention");
});

test("no approved facts produces an actionable warning without approved eligibility", () => {
  const facts = makeFacts().map((fact) => ({ ...fact, status: "rejected" as const }));
  const result = validateNorthstarPreproduction(facts, makeBrief(), cloneInitialStoryboard());
  assert.equal(result.factSummary.approved, 0);
  assert.equal(result.factSummary.eligibleFacts.length, 0);
  assert.ok(findById(result.findings, "facts.none-approved"));
});

test("empty storyboard and a storyboard without previewable content are blockers", () => {
  const empty = validateNorthstarPreproduction(makeFacts(), makeBrief(), []);
  assert.ok(findById(empty.findings, "storyboard.empty"));
  assert.equal(empty.storyboardSummary.plannedRuntimeSeconds, null);
  assert.equal(empty.storyboardSummary.runtimeUnavailableReason, "empty");

  const noContent = cloneInitialStoryboard().map((scene) => ({
    ...scene,
    visualDirection: "",
    onScreenText: "",
    narration: "",
  }));
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), noContent);
  assert.ok(findById(result.findings, "storyboard.no-usable-content"));
});

test("on-screen text and narration are optional when visual direction is present", () => {
  const scenes = cloneInitialStoryboard().map((scene) => ({ ...scene, onScreenText: "", narration: "" }));
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), scenes);
  assert.equal(result.findings.some((finding) => finding.id.includes("onScreenText") || finding.id.includes("narration")), false);
  assert.equal(result.findings.some((finding) => finding.blocksReadiness), false);
});

test("blank title and missing visual direction identify the stable scene", () => {
  const scenes = cloneInitialStoryboard();
  scenes[0] = { ...scenes[0], title: "  ", visualDirection: "" };
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), scenes);
  assert.equal(findById(result.findings, `storyboard.title-missing.${scenes[0].id}`)?.affectedSceneId, scenes[0].id);
  assert.equal(findById(result.findings, `storyboard.visual-direction-missing.${scenes[0].id}`)?.destinationRoutes[0], "/projects/sample-northstar/storyboard");
});

test("invalid whole-second duration blocks readiness and makes planned runtime unavailable", () => {
  const scenes = cloneInitialStoryboard();
  scenes[0] = { ...scenes[0], durationSeconds: 2.5 };
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), scenes);
  assert.ok(findById(result.findings, `storyboard.duration-invalid.${scenes[0].id}`));
  assert.equal(result.storyboardSummary.plannedRuntimeSeconds, null);
  assert.equal(result.storyboardSummary.runtimeUnavailableReason, "invalid-scene-duration");
});

test("runtime mismatch is derived in seconds without modifying source data", () => {
  const facts = makeFacts();
  const brief = makeBrief();
  const scenes = cloneInitialStoryboard();
  scenes[0] = { ...scenes[0], durationSeconds: 8 };
  const result = validateNorthstarPreproduction(facts, brief, scenes);
  assert.equal(result.storyboardSummary.plannedRuntimeSeconds, 19);
  assert.equal(result.storyboardSummary.targetRuntimeSeconds, 15);
  assert.equal(result.storyboardSummary.runtimeDifferenceSeconds, 4);
  assert.match(findById(result.findings, "runtime.target-mismatch")?.explanation ?? "", /4 seconds longer/);
  assert.equal(scenes[0].durationSeconds, 8);
  assert.equal(brief.duration, 15);
});

test("storyboard add, delete, and reorder helpers preserve scene identity and content", () => {
  const original = cloneInitialStoryboard();
  const newScene: StoryboardScene = { ...original[0], id: "added-scene", title: "Added scene" };
  const appended = appendStoryboardScene(original, newScene);
  assert.equal(appended.length, original.length + 1);
  const deleted = deleteStoryboardScene(appended, newScene.id);
  assert.deepEqual(deleted, original);
  const moved = moveStoryboardScene(original, original[1].id, -1);
  assert.deepEqual(moved.map((scene) => scene.id), [original[1].id, original[0].id, original[2].id]);
  assert.equal(moved[0].title, original[1].title);
  assert.equal(moved[0].visualDirection, original[1].visualDirection);
});

test("exact normalized matching flags unreviewed, rejected, and demo-approved claims", () => {
  const facts = makeFacts();
  const scenes = cloneInitialStoryboard();
  scenes[0] = { ...scenes[0], onScreenText: "  SMALL-BATCH   ROASTED COFFEE  ", narration: "A good cup, made simple." };
  scenes[1] = { ...scenes[1], onScreenText: "people looking for a considered everyday cup" };
  const result = validateNorthstarPreproduction(facts, makeBrief(), scenes);
  assert.equal(findById(result.findings, `grounding.exact-match.${scenes[0].id}.product`)?.severity, "warning");
  assert.equal(findById(result.findings, `grounding.exact-match.${scenes[0].id}.message`)?.severity, "warning");
  assert.equal(findById(result.findings, `grounding.exact-match.${scenes[1].id}.audience`)?.severity, "info");
  assert.ok(findById(result.findings, "grounding.exact-match-limitations"));
});

test("unmatched creative copy is not described as verified", () => {
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), cloneInitialStoryboard());
  const limitation = findById(result.findings, "grounding.exact-match-limitations");
  assert.match(limitation?.explanation ?? "", /not analyzed and are not thereby verified or safe/);
});

test("duplicate scene IDs are detected without index-derived scene finding IDs", () => {
  const scenes = cloneInitialStoryboard();
  scenes[1] = { ...scenes[1], id: scenes[0].id };
  const result = validateNorthstarPreproduction(makeFacts(), makeBrief(), scenes);
  assert.ok(findById(result.findings, "storyboard.invalid-scenes-or-identifiers"));
  assert.equal(new Set(result.findings.map((finding) => finding.id)).size, result.findings.length);
});

test("readiness is blocker-derived and finding order and IDs are deterministic", () => {
  const facts = makeFacts();
  const brief = makeBrief({ requirementsConfirmed: false });
  const scenes = cloneInitialStoryboard();
  const first = validateNorthstarPreproduction(facts, brief, scenes);
  const second = validateNorthstarPreproduction(facts, brief, scenes);
  assert.equal(first.status, "needs-attention");
  assert.deepEqual(first.findings.map((finding) => finding.id), second.findings.map((finding) => finding.id));
  assert.deepEqual(first.findings.map((finding) => finding.severity), [...first.findings.map((finding) => finding.severity)].sort((a, b) => severityOrder[a] - severityOrder[b]));
  assert.equal(first.status === "needs-attention", first.blockerCount > 0);
});

test("validation does not mutate facts, revisions, brief, or ordered scenes", () => {
  const facts = makeFacts();
  const brief = makeBrief();
  const scenes = cloneInitialStoryboard();
  const before = JSON.stringify({ facts, brief, scenes });
  validateNorthstarPreproduction(facts, brief, scenes);
  assert.equal(JSON.stringify({ facts, brief, scenes }), before);
});
