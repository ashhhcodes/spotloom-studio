import {
  deriveReviewStatusCounts,
  getApprovedDemoFacts,
  type ProjectFact,
  type ReviewStatus,
} from "./review/demo-facts.ts";
import type { CreativeBrief } from "./creative-brief";
import { calculateStoryboardRuntime, isValidStoryboardDuration, type StoryboardScene } from "./storyboard-model.ts";

export type FindingSeverity = "blocker" | "warning" | "info";
export type FindingCategory = "brief" | "facts" | "storyboard" | "runtime" | "grounding" | "production";
export type WorkspaceRoute =
  | "/projects/sample-northstar/brief"
  | "/projects/sample-northstar/review"
  | "/projects/sample-northstar/storyboard"
  | "/projects/sample-northstar/creative";

export type PreproductionFinding = {
  id: string;
  severity: FindingSeverity;
  category: FindingCategory;
  title: string;
  explanation: string;
  resolution: string;
  destinationRoutes: WorkspaceRoute[];
  blocksReadiness: boolean;
  affectedFactId?: string;
  affectedSceneId?: string;
};

export type ReadinessStatus = "needs-attention" | "ready-for-human-review";

export type PreproductionValidationResult = {
  /** Structural readiness never removes the project's overarching demo-only boundary. */
  status: ReadinessStatus;
  projectBoundary: "demo-only";
  findings: PreproductionFinding[];
  blockerCount: number;
  warningCount: number;
  infoCount: number;
  factSummary: {
    total: number;
    approved: number;
    unreviewed: number;
    rejected: number;
    invalidStatus: number;
    eligibleFacts: ProjectFact[];
  };
  storyboardSummary: {
    sceneCount: number;
    plannedRuntimeSeconds: number | null;
    targetRuntimeSeconds: number | null;
    runtimeDifferenceSeconds: number | null;
    runtimeUnavailableReason: "empty" | "invalid-scene-duration" | "invalid-target" | null;
  };
};

const reviewStatuses: readonly ReviewStatus[] = ["unreviewed", "approved", "rejected"];
const objectives = ["awareness", "engagement", "traffic", "conversions"] as const;
const platforms = ["instagram", "tiktok", "youtube", "other"] as const;
const aspectRatios = ["9:16", "1:1", "16:9"] as const;
const briefDurations = [15, 30, 60] as const;
const categoryOrder: FindingCategory[] = ["brief", "facts", "storyboard", "runtime", "grounding", "production"];
const severityOrder: Record<FindingSeverity, number> = { blocker: 0, warning: 1, info: 2 };
const briefRoute: WorkspaceRoute = "/projects/sample-northstar/brief";
const reviewRoute: WorkspaceRoute = "/projects/sample-northstar/review";
const storyboardRoute: WorkspaceRoute = "/projects/sample-northstar/storyboard";
const readinessRoute: WorkspaceRoute = "/projects/sample-northstar/creative";

function isOneOf<T extends string | number>(value: unknown, choices: readonly T[]): value is T {
  return choices.some((choice) => choice === value);
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Exact, case-insensitive, whitespace-normalized matching only. This is not semantic grounding. */
function normalizeClaim(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function addFinding(
  findings: PreproductionFinding[],
  finding: PreproductionFinding,
) {
  findings.push(finding);
}

/**
 * Pure local checks for Northstar's current brief, reviewed facts, and ordered scenes.
 * “Ready for human review” means only that local structure is complete and explicitly
 * confirmed. It never means facts are verified, policy-checked, or ready to publish.
 */
export function validateNorthstarPreproduction(
  facts: readonly ProjectFact[],
  brief: CreativeBrief,
  scenes: readonly StoryboardScene[],
): PreproductionValidationResult {
  const findings: PreproductionFinding[] = [];
  const briefRecord: Record<string, unknown> = isRecord(brief) ? brief : {};
  const scenesAreArray = Array.isArray(scenes);
  const rawScenes: readonly unknown[] = scenesAreArray ? scenes : [];

  const addBriefBlocker = (id: string, title: string, explanation: string, resolution: string) => addFinding(findings, {
    id, severity: "blocker", category: "brief", title, explanation, resolution,
    destinationRoutes: [briefRoute], blocksReadiness: true,
  });

  const requiredTextFields = [
    ["targetAudience", "Target audience"],
    ["productOrOffer", "Product or offer"],
    ["keyMessage", "Key message"],
    ["tone", "Tone and creative direction"],
    ["callToAction", "Call to action"],
  ] as const;
  for (const [field, label] of requiredTextFields) {
    if (!nonEmpty(briefRecord[field])) {
      addBriefBlocker(
        `brief.required.${field}`,
        `${label} is missing`,
        `The ${label.toLowerCase()} field is empty or contains only whitespace.`,
        `Enter a ${label.toLowerCase()} in the Creative Brief.`,
      );
    }
  }
  if (typeof briefRecord.valueProposition !== "string") {
    addBriefBlocker("brief.invalid.valueProposition", "Value proposition is invalid", "The optional value proposition must be text when provided.", "Replace it with text or clear the field in the Creative Brief.");
  }

  const requiredChoices: { field: string; label: string; choices: readonly (string | number)[] }[] = [
    { field: "objective", label: "Campaign objective", choices: objectives },
    { field: "platform", label: "Platform", choices: platforms },
    { field: "aspectRatio", label: "Aspect ratio", choices: aspectRatios },
    { field: "duration", label: "Target duration", choices: briefDurations },
  ];
  for (const { field, label, choices } of requiredChoices) {
    if (!isOneOf(briefRecord[field], choices)) {
      addBriefBlocker(
        `brief.selection.${field}`,
        `${label} needs a valid selection`,
        `The ${label.toLowerCase()} is missing or is not one of the supported options.`,
        `Choose a supported ${label.toLowerCase()} in the Creative Brief.`,
      );
    }
  }
  if (briefRecord.requirementsConfirmed !== true) {
    addBriefBlocker(
      "brief.confirmation.required",
      "Demo brief needs human confirmation",
      "Prefilled demo defaults are not evidence that campaign requirements were supplied or confirmed.",
      "Review the current planning choices and confirm the brief in the Creative Brief. This does not verify business facts.",
    );
  }

  addFinding(findings, {
    id: "brief.demo-defaults",
    severity: "info",
    category: "brief",
    title: "Brief values began as illustrative defaults",
    explanation: "The Northstar values are sample planning content. A confirmation is a local human review signal, not evidence of real campaign requirements or business facts.",
    resolution: "Keep the demo label visible and replace defaults with actual requirements in a future connected workflow.",
    destinationRoutes: [briefRoute],
    blocksReadiness: false,
  });

  const validFactStatuses = facts.filter((fact) => isOneOf(fact.status, reviewStatuses));
  const factCounts = deriveReviewStatusCounts(validFactStatuses);
  const factIdCounts = new Map<string, number>();
  for (const fact of facts) {
    if (typeof fact.id === "string" && fact.id.trim()) factIdCounts.set(fact.id, (factIdCounts.get(fact.id) ?? 0) + 1);
  }
  const invalidFactIds = facts.filter((fact) => typeof fact.id !== "string" || !fact.id.trim() || factIdCounts.get(fact.id) !== 1);
  const uniquelyIdentifiedFacts = validFactStatuses.filter((fact) => typeof fact.id === "string" && Boolean(fact.id.trim()) && factIdCounts.get(fact.id) === 1);
  const eligibleFacts = getApprovedDemoFacts(uniquelyIdentifiedFacts);
  if (invalidFactIds.length > 0) {
    addFinding(findings, {
      id: "facts.invalid-identifiers",
      severity: "blocker",
      category: "facts",
      title: "Fact identifiers are missing or duplicated",
      explanation: `${invalidFactIds.length} fact ${invalidFactIds.length === 1 ? "entry has" : "entries have"} an identifier that cannot be referenced uniquely.`,
      resolution: "Repair the affected fact identifiers before reviewing these facts.",
      destinationRoutes: [reviewRoute],
      blocksReadiness: true,
    });
  }

  for (const fact of facts) {
    if (typeof fact.id !== "string" || !fact.id.trim() || factIdCounts.get(fact.id) !== 1) continue;
    if (!isOneOf(fact.status, reviewStatuses)) {
      addFinding(findings, {
        id: `facts.invalid-status.${fact.id}`,
        severity: "blocker",
        category: "facts",
        title: "Fact review status is invalid",
        explanation: `The review status for “${fact.claim}” is not recognized. It cannot be considered eligible.`,
        resolution: "Review the fact and restore a supported status.",
        destinationRoutes: [reviewRoute],
        blocksReadiness: true,
        affectedFactId: fact.id,
      });
    } else if (fact.status === "unreviewed") {
      addFinding(findings, {
        id: `facts.unreviewed.${fact.id}`,
        severity: "warning",
        category: "facts",
        title: `Review the unreviewed ${fact.category.toLowerCase()} fact`,
        explanation: `“${fact.claim}” has not been reviewed and is not eligible as an approved demo claim.`,
        resolution: "Review this fact or remove any unsupported use from the storyboard.",
        destinationRoutes: [reviewRoute],
        blocksReadiness: false,
        affectedFactId: fact.id,
      });
    } else if (fact.status === "rejected") {
      addFinding(findings, {
        id: `facts.rejected.${fact.id}`,
        severity: "warning",
        category: "facts",
        title: `Remove or revisit the rejected ${fact.category.toLowerCase()} fact`,
        explanation: `“${fact.claim}” was rejected for this demo and is excluded from the approved-fact collection.`,
        resolution: "Do not use this claim in demo copy; revisit it in Fact Review or remove it from creative text.",
        destinationRoutes: [reviewRoute],
        blocksReadiness: false,
        affectedFactId: fact.id,
      });
    }
  }
  if (eligibleFacts.length === 0) {
    addFinding(findings, {
      id: "facts.none-approved",
      severity: "warning",
      category: "facts",
      title: "No facts are approved for demo use",
      explanation: "The current review state has no facts eligible for the limited demo workflow.",
      resolution: "Review relevant facts. Approval remains a demo decision and does not independently verify a claim.",
      destinationRoutes: [reviewRoute],
      blocksReadiness: false,
    });
  }

  const sceneIdCounts = new Map<string, number>();
  for (const rawScene of rawScenes) {
    if (!isRecord(rawScene)) continue;
    const id = rawScene.id;
    if (typeof id === "string" && id.trim()) sceneIdCounts.set(id, (sceneIdCounts.get(id) ?? 0) + 1);
  }
  const malformedSceneCount = rawScenes.filter((scene) => !isRecord(scene)).length;
  const invalidSceneIdCount = rawScenes.filter((scene) => !isRecord(scene) || typeof scene.id !== "string" || !scene.id.trim() || sceneIdCounts.get(scene.id) !== 1).length;
  if (!scenesAreArray || malformedSceneCount > 0 || invalidSceneIdCount > 0) {
    addFinding(findings, {
      id: "storyboard.invalid-scenes-or-identifiers",
      severity: "blocker",
      category: "storyboard",
      title: "Storyboard scenes cannot be identified reliably",
      explanation: "One or more scene records are malformed or have a missing or duplicated stable ID.",
      resolution: "Restore valid scene records with unique, nonempty IDs in the Storyboard.",
      destinationRoutes: [storyboardRoute],
      blocksReadiness: true,
    });
  }

  if (rawScenes.length === 0) {
    addFinding(findings, {
      id: "storyboard.empty",
      severity: "blocker",
      category: "storyboard",
      title: "Storyboard is empty",
      explanation: "There are no scenes from which to plan or preview a sequence.",
      resolution: "Add at least one illustrative scene in the Storyboard.",
      destinationRoutes: [storyboardRoute],
      blocksReadiness: true,
    });
  }

  const validScenes = rawScenes.filter((scene): scene is Record<string, unknown> =>
    isRecord(scene) && typeof scene.id === "string" && Boolean(scene.id.trim()) && sceneIdCounts.get(scene.id) === 1,
  );
  const anyPreviewableContent = validScenes.some((scene) =>
    nonEmpty(scene.visualDirection) || nonEmpty(scene.onScreenText) || nonEmpty(scene.narration),
  );
  if (validScenes.length > 0 && !anyPreviewableContent) {
    addFinding(findings, {
      id: "storyboard.no-usable-content",
      severity: "blocker",
      category: "storyboard",
      title: "Storyboard has no usable scene content",
      explanation: "No scene contains visual direction, on-screen text, or narration to communicate a previewable idea.",
      resolution: "Add visual direction or intentional scene copy in the Storyboard.",
      destinationRoutes: [storyboardRoute],
      blocksReadiness: true,
    });
  }

  const invalidDurationIds: string[] = [];
  for (const scene of validScenes) {
    const sceneId = scene.id as string;
    if (!nonEmpty(scene.title)) {
      addFinding(findings, {
        id: `storyboard.title-missing.${sceneId}`,
        severity: "blocker",
        category: "storyboard",
        title: "Scene title is missing",
        explanation: "This scene has an empty or whitespace-only title.",
        resolution: "Add a concise title that identifies this scene.",
        destinationRoutes: [storyboardRoute],
        blocksReadiness: true,
        affectedSceneId: sceneId,
      });
    }
    if (anyPreviewableContent && !nonEmpty(scene.visualDirection)) {
      addFinding(findings, {
        id: `storyboard.visual-direction-missing.${sceneId}`,
        severity: "blocker",
        category: "storyboard",
        title: "Visual direction is missing",
        explanation: `Scene “${nonEmpty(scene.title) ? scene.title : "Untitled scene"}” has no visual direction.`,
        resolution: "Describe an illustrative visual approach or remove the scene.",
        destinationRoutes: [storyboardRoute],
        blocksReadiness: true,
        affectedSceneId: sceneId,
      });
    }
    if (!nonEmpty(scene.narrativePurpose)) {
      addFinding(findings, {
        id: `storyboard.purpose-missing.${sceneId}`,
        severity: "blocker",
        category: "storyboard",
        title: "Scene narrative purpose is missing",
        explanation: `Scene “${nonEmpty(scene.title) ? scene.title : "Untitled scene"}” does not explain its role in the sequence.`,
        resolution: "Describe what this scene is intended to communicate.",
        destinationRoutes: [storyboardRoute],
        blocksReadiness: true,
        affectedSceneId: sceneId,
      });
    }
    if (!isValidStoryboardDuration(scene.durationSeconds)) {
      invalidDurationIds.push(sceneId);
      addFinding(findings, {
        id: `storyboard.duration-invalid.${sceneId}`,
        severity: "blocker",
        category: "storyboard",
        title: "Scene duration is invalid",
        explanation: `Scene “${nonEmpty(scene.title) ? scene.title : "Untitled scene"}” must use a whole number from 1 to 60 seconds.`,
        resolution: "Enter a whole-number duration between 1 and 60 seconds.",
        destinationRoutes: [storyboardRoute],
        blocksReadiness: true,
        affectedSceneId: sceneId,
      });
    }
  }

  const targetDuration = isOneOf(briefRecord.duration, briefDurations) ? briefRecord.duration : null;
  const hasInvalidSceneDuration = invalidDurationIds.length > 0 || validScenes.length !== rawScenes.length;
  const plannedRuntime = rawScenes.length > 0 && !hasInvalidSceneDuration
    ? calculateStoryboardRuntime(validScenes.map((scene) => scene.durationSeconds))
    : null;
  const runtimeDifference = plannedRuntime !== null && targetDuration !== null
    ? plannedRuntime - targetDuration
    : null;
  let runtimeUnavailableReason: PreproductionValidationResult["storyboardSummary"]["runtimeUnavailableReason"] = null;
  if (rawScenes.length === 0) runtimeUnavailableReason = "empty";
  else if (hasInvalidSceneDuration) runtimeUnavailableReason = "invalid-scene-duration";
  else if (targetDuration === null) runtimeUnavailableReason = "invalid-target";

  if (runtimeDifference !== null && runtimeDifference !== 0) {
    const difference = Math.abs(runtimeDifference);
    const relation = runtimeDifference > 0 ? "longer" : "shorter";
    addFinding(findings, {
      id: "runtime.target-mismatch",
      severity: "warning",
      category: "runtime",
      title: "Resolve the runtime mismatch",
      explanation: `The planned sequence is ${difference} ${difference === 1 ? "second" : "seconds"} ${relation} than the ${targetDuration}-second brief target.`,
      resolution: "Review the target in the Creative Brief or edit scene durations. No values are changed automatically.",
      destinationRoutes: [storyboardRoute, briefRoute],
      blocksReadiness: false,
    });
  }

  const eligibleFactIds = new Set(eligibleFacts.map((fact) => fact.id));
  const factsByNormalizedClaim = new Map<string, ProjectFact[]>();
  for (const fact of facts) {
    if (typeof fact.id !== "string" || !fact.id.trim() || factIdCounts.get(fact.id) !== 1 || !isOneOf(fact.status, reviewStatuses) || !nonEmpty(fact.claim)) continue;
    const normalized = normalizeClaim(fact.claim);
    const matches = factsByNormalizedClaim.get(normalized) ?? [];
    matches.push(fact);
    factsByNormalizedClaim.set(normalized, matches);
  }
  for (const scene of validScenes) {
    const channels = [
      ["on-screen text", scene.onScreenText],
      ["narration", scene.narration],
    ] as const;
    const matchesByFact = new Map<string, { fact: ProjectFact; channels: string[] }>();
    for (const [channel, rawText] of channels) {
      if (!nonEmpty(rawText)) continue;
      const matches = factsByNormalizedClaim.get(normalizeClaim(rawText)) ?? [];
      for (const fact of matches) {
        const entry = matchesByFact.get(fact.id) ?? { fact, channels: [] };
        entry.channels.push(channel);
        matchesByFact.set(fact.id, entry);
      }
    }
    for (const { fact, channels: matchedChannels } of matchesByFact.values()) {
      const approved = eligibleFactIds.has(fact.id);
      const statusSeverity: FindingSeverity = approved ? "info" : "warning";
      const statusText = approved ? "approved for this demo only" : fact.status === "rejected" ? "rejected and excluded from approved demo content" : "unreviewed and not eligible as approved demo content";
      addFinding(findings, {
        id: `grounding.exact-match.${scene.id}.${fact.id}`,
        severity: statusSeverity,
        category: "grounding",
        title: approved ? "Scene copy matches a demo-approved fact" : "Scene copy matches an unsupported fact",
        explanation: `The ${matchedChannels.join(" and ")} in scene “${nonEmpty(scene.title) ? scene.title : "Untitled scene"}” exactly matches “${fact.claim}”, which is ${statusText}. This match does not establish truth.`,
        resolution: approved ? "Keep the demo-only label; do not treat this match or approval as independent verification." : "Review or remove this claim in the Storyboard and resolve the fact status in Fact Review.",
        destinationRoutes: [storyboardRoute, reviewRoute],
        blocksReadiness: false,
        affectedFactId: fact.id,
        affectedSceneId: scene.id as string,
      });
    }
  }

  addFinding(findings, {
    id: "grounding.exact-match-limitations",
    severity: "info",
    category: "grounding",
    title: "Claim matching is intentionally limited",
    explanation: "Only exact text matches after case folding and whitespace normalization are associated with facts. Unmatched copy and paraphrases are not analyzed and are not thereby verified or safe.",
    resolution: "Manually review all creative text against source evidence; this demo has no independently collected evidence.",
    destinationRoutes: [storyboardRoute, reviewRoute],
    blocksReadiness: false,
  });

  addFinding(findings, {
    id: "production.demo-only-boundary",
    severity: "info",
    category: "production",
    title: "Demo only — production checks are not implemented",
    explanation: "This is a local deterministic pre-production check. Content is illustrative; there is no independent source verification, semantic AI analysis, or legal or advertising-policy review. The separate local render creates only a temporary silent illustrative MP4, not production media.",
    resolution: "Use this result only to organize a human review. Passing checks does not establish factual accuracy or publication safety.",
    destinationRoutes: [readinessRoute],
    blocksReadiness: false,
  });

  const uniqueFindings = [...new Map(findings.map((finding) => [finding.id, finding])).values()];
  uniqueFindings.sort((a, b) =>
    severityOrder[a.severity] - severityOrder[b.severity]
    || categoryOrder.indexOf(a.category) - categoryOrder.indexOf(b.category)
    || compareText(a.affectedFactId ?? a.affectedSceneId ?? a.id, b.affectedFactId ?? b.affectedSceneId ?? b.id)
    || compareText(a.id, b.id),
  );
  const blockerCount = uniqueFindings.filter((finding) => finding.blocksReadiness).length;

  return {
    status: blockerCount > 0 ? "needs-attention" : "ready-for-human-review",
    projectBoundary: "demo-only",
    findings: uniqueFindings,
    blockerCount,
    warningCount: uniqueFindings.filter((finding) => finding.severity === "warning").length,
    infoCount: uniqueFindings.filter((finding) => finding.severity === "info").length,
    factSummary: {
      total: facts.length,
      approved: factCounts.approved,
      unreviewed: factCounts.unreviewed,
      rejected: factCounts.rejected,
      invalidStatus: facts.length - validFactStatuses.length,
      eligibleFacts,
    },
    storyboardSummary: {
      sceneCount: rawScenes.length,
      plannedRuntimeSeconds: plannedRuntime,
      targetRuntimeSeconds: targetDuration,
      runtimeDifferenceSeconds: runtimeDifference,
      runtimeUnavailableReason,
    },
  };
}
