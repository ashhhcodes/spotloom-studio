import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const testDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(testDir, "..", "..");
const frontendRoot = join(repoRoot, "frontend");
const modelRoot = join(frontendRoot, "src", "app", "projects", "sample-northstar");
const fixture = JSON.parse(readFileSync(join(testDir, "fixtures", "contract-compatibility.json"), "utf8"));
const scratch = mkdtempSync(join(testDir, ".frontend-contract-check-"));
const tsc = join(frontendRoot, "node_modules", "typescript", "bin", "tsc");
const node = process.execPath;

function moduleReference(fromDirectory, sourcePath) {
  let value = relative(fromDirectory, sourcePath).replaceAll("\\", "/");
  if (!value.startsWith(".")) value = `./${value}`;
  return value;
}

try {
  const typeHarness = join(scratch, "fixture-types.ts");
  const typeSource = `
import type { ProjectFact } from ${JSON.stringify(moduleReference(scratch, join(modelRoot, "review", "demo-facts")))};
import type { CreativeBrief } from ${JSON.stringify(moduleReference(scratch, join(modelRoot, "creative-brief")))};
import type { StoryboardScene } from ${JSON.stringify(moduleReference(scratch, join(modelRoot, "storyboard-model")))};
const fixture = ${JSON.stringify(fixture.validNorthstar)} satisfies {
  facts: ProjectFact[];
  brief: CreativeBrief;
  storyboard: { scenes: StoryboardScene[] };
};
void fixture;
`;
  writeFileSync(typeHarness, typeSource, "utf8");
  execFileSync(node, [tsc,
    "--noEmit", "--strict", "--esModuleInterop", "--resolveJsonModule",
    "--moduleResolution", "bundler", "--module", "esnext", "--target", "ES2020",
    "--skipLibCheck", typeHarness,
  ], { cwd: repoRoot, stdio: "inherit" });

  const compiled = join(scratch, "compiled");
  const sources = [
    join(modelRoot, "review", "demo-facts.ts"),
    join(modelRoot, "creative-brief.ts"),
    join(modelRoot, "storyboard-model.ts"),
    join(modelRoot, "preproduction-validation.ts"),
  ];
  execFileSync(node, [tsc,
    "--target", "ES2020", "--module", "commonjs", "--moduleResolution", "node",
    "--strict", "--skipLibCheck", "--rootDir", modelRoot, "--outDir", compiled,
    ...sources,
  ], { cwd: repoRoot, stdio: "inherit" });

  const require = createRequire(join(compiled, "contract-runner.cjs"));
  const factsModule = require(join(compiled, "review", "demo-facts.js"));
  const briefModule = require(join(compiled, "creative-brief.js"));
  const storyboardModule = require(join(compiled, "storyboard-model.js"));
  const readinessModule = require(join(compiled, "preproduction-validation.js"));
  const valid = fixture.validNorthstar;

  assert.deepEqual(valid.facts, factsModule.northstarDemoProject.facts);
  assert.deepEqual(valid.brief, briefModule.initialNorthstarBrief);
  assert.deepEqual(valid.storyboard.scenes, storyboardModule.initialNorthstarStoryboard);
  assert.deepEqual(factsModule.deriveReviewStatusCounts(valid.facts), {
    unreviewed: 1,
    approved: 1,
    rejected: 1,
  });
  assert.deepEqual(factsModule.getApprovedDemoFacts(valid.facts).map((fact) => fact.id), ["audience"]);

  const readiness = readinessModule.validateNorthstarPreproduction(
    valid.facts, valid.brief, valid.storyboard.scenes,
  );
  assert.equal(readiness.storyboardSummary.plannedRuntimeSeconds, 15);
  assert.ok(readiness.findings.some((finding) => finding.id === "brief.confirmation.required"));

  const boundaryScenes = fixture.boundaryDurationScenes;
  assert.equal(storyboardModule.calculateStoryboardRuntime(boundaryScenes.map((scene) => scene.durationSeconds)), 61);

  const badDuration = structuredClone(valid);
  badDuration.storyboard.scenes[0].durationSeconds = fixture.mutations.invalidDuration;
  assert.equal(storyboardModule.calculateStoryboardRuntime(
    badDuration.storyboard.scenes.map((scene) => scene.durationSeconds),
  ), null);
  assert.ok(readinessModule.validateNorthstarPreproduction(
    badDuration.facts, badDuration.brief, badDuration.storyboard.scenes,
  ).findings.some((finding) => finding.id === "storyboard.duration-invalid.northstar-scene-opening"));

  const emptyBoard = structuredClone(valid);
  emptyBoard.storyboard.scenes = [];
  assert.equal(storyboardModule.calculateStoryboardRuntime([]), null);
  assert.ok(readinessModule.validateNorthstarPreproduction(
    emptyBoard.facts, emptyBoard.brief, emptyBoard.storyboard.scenes,
  ).findings.some((finding) => finding.id === "storyboard.empty"));

  const unknownEnum = structuredClone(valid);
  unknownEnum.brief.objective = fixture.mutations.unknownObjective;
  assert.ok(readinessModule.validateNorthstarPreproduction(
    unknownEnum.facts, unknownEnum.brief, unknownEnum.storyboard.scenes,
  ).findings.some((finding) => finding.id === "brief.selection.objective"));

  const missingField = structuredClone(valid);
  delete missingField.brief[fixture.mutations.removedBriefField];
  assert.ok(readinessModule.validateNorthstarPreproduction(
    missingField.facts, missingField.brief, missingField.storyboard.scenes,
  ).findings.some((finding) => finding.id === "brief.required.targetAudience"));

  const duplicateFact = structuredClone(valid);
  duplicateFact.facts[1].id = fixture.mutations.duplicateFactId;
  assert.ok(readinessModule.validateNorthstarPreproduction(
    duplicateFact.facts, duplicateFact.brief, duplicateFact.storyboard.scenes,
  ).findings.some((finding) => finding.id === "facts.invalid-identifiers"));

  const duplicateScene = structuredClone(valid);
  duplicateScene.storyboard.scenes[1].id = fixture.mutations.duplicateSceneId;
  assert.ok(readinessModule.validateNorthstarPreproduction(
    duplicateScene.facts, duplicateScene.brief, duplicateScene.storyboard.scenes,
  ).findings.some((finding) => finding.id === "storyboard.invalid-scenes-or-identifiers"));

  const extraProperty = structuredClone(valid);
  extraProperty.brief[fixture.mutations.extraFieldName] = fixture.mutations.extraFieldValue;
  const extraIgnored = readinessModule.validateNorthstarPreproduction(
    extraProperty.facts, extraProperty.brief, extraProperty.storyboard.scenes,
  );
  assert.deepEqual(extraIgnored.findings.map((finding) => finding.id), readiness.findings.map((finding) => finding.id));

  const emptyPurpose = structuredClone(valid);
  emptyPurpose.storyboard.scenes[0].narrativePurpose = fixture.mutations.emptyNarrativePurpose;
  assert.ok(readinessModule.validateNorthstarPreproduction(
    emptyPurpose.facts, emptyPurpose.brief, emptyPurpose.storyboard.scenes,
  ).findings.some((finding) => finding.id === "storyboard.purpose-missing.northstar-scene-opening"));

  const untrustedRuntime = structuredClone(valid);
  untrustedRuntime.storyboard.plannedRuntimeSeconds = fixture.mutations.callerRuntime;
  assert.equal(storyboardModule.calculateStoryboardRuntime(
    untrustedRuntime.storyboard.scenes.map((scene) => scene.durationSeconds),
  ), 15);

  const corrected = factsModule.correctDemoFact(valid.facts[0], "Revised illustrative claim");
  assert.equal(corrected.status, "unreviewed");
  assert.deepEqual(corrected.revisions, [valid.facts[0].claim]);

  console.log("Frontend contract fixture types: passed");
  console.log("Frontend model/helper compatibility assertions: passed");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
