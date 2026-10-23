"""Deterministic, limited pre-production findings for submitted contract data."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from .integration_schemas import (
    BusinessClaim,
    BusinessClaims,
    CreativeBrief,
    StoryboardInput,
    calculate_storyboard_runtime,
)


FindingSeverity = Literal["blocker", "warning", "info"]
FindingCategory = Literal["brief", "facts", "storyboard", "runtime", "grounding", "production"]
WorkspaceRoute = Literal[
    "/projects/sample-northstar/brief",
    "/projects/sample-northstar/review",
    "/projects/sample-northstar/storyboard",
    "/projects/sample-northstar/creative",
]
ReadinessStatus = Literal["needs-attention", "ready-for-human-review"]
EvaluationStatus = Literal["evaluated-with-limitations"]
_REVIEW_ROUTE: WorkspaceRoute = "/projects/sample-northstar/review"
_BRIEF_ROUTE: WorkspaceRoute = "/projects/sample-northstar/brief"
_STORYBOARD_ROUTE: WorkspaceRoute = "/projects/sample-northstar/storyboard"
_READINESS_ROUTE: WorkspaceRoute = "/projects/sample-northstar/creative"
_CATEGORIES: tuple[FindingCategory, ...] = (
    "brief", "facts", "storyboard", "runtime", "grounding", "production",
)
_SEVERITIES: dict[FindingSeverity, int] = {"blocker": 0, "warning": 1, "info": 2}
_JS_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001"
    "\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_NORMALIZE_WHITESPACE = re.compile(
    r"[\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)


class PreproductionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    severity: FindingSeverity
    category: FindingCategory
    title: StrictStr
    explanation: StrictStr
    resolution: StrictStr
    destinationRoutes: list[WorkspaceRoute] = Field(max_length=4)
    blocksReadiness: StrictBool
    affectedFactId: StrictStr | None = None
    affectedSceneId: StrictStr | None = None


class FindingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    blockerCount: StrictInt = Field(ge=0)
    warningCount: StrictInt = Field(ge=0)
    infoCount: StrictInt = Field(ge=0)


class FactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    total: StrictInt = Field(ge=0)
    callerMarkedApproved: StrictInt = Field(ge=0)
    unreviewed: StrictInt = Field(ge=0)
    rejected: StrictInt = Field(ge=0)
    invalidStatus: StrictInt = Field(ge=0)
    eligibleFactIds: list[StrictStr] = Field(max_length=32)


class StoryboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sceneCount: StrictInt = Field(ge=0)
    plannedRuntimeSeconds: StrictInt | None
    targetRuntimeSeconds: StrictInt
    runtimeDifferenceSeconds: StrictInt | None
    runtimeUnavailableReason: Literal["empty"] | None


class PreproductionValidationResponse(BaseModel):
    """Supported findings, separately labeled from verification and full readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requestSchemaValid: StrictBool
    evaluationStatus: EvaluationStatus
    readinessStatus: ReadinessStatus
    briefConfirmationSignal: Literal["caller-declared-confirmed", "not-confirmed"]
    factualVerification: Literal["not-performed"]
    findings: list[PreproductionFinding]
    summary: FindingSummary
    factSummary: FactSummary
    storyboardSummary: StoryboardSummary


def _nonempty(value: str) -> bool:
    return bool(value.strip())


def _normalize_claim(value: str) -> str:
    """Match the frontend's trim, whitespace-collapse, and lowercase comparison."""
    return _NORMALIZE_WHITESPACE.sub(" ", value.strip(_JS_WHITESPACE)).lower()


def _finding(
    finding_id: str,
    severity: FindingSeverity,
    category: FindingCategory,
    title: str,
    explanation: str,
    resolution: str,
    routes: list[WorkspaceRoute],
    blocks_readiness: bool,
    *,
    fact_id: str | None = None,
    scene_id: str | None = None,
) -> PreproductionFinding:
    return PreproductionFinding(
        id=finding_id,
        severity=severity,
        category=category,
        title=title,
        explanation=explanation,
        resolution=resolution,
        destinationRoutes=routes,
        blocksReadiness=blocks_readiness,
        affectedFactId=fact_id,
        affectedSceneId=scene_id,
    )


def evaluate_preproduction(
    facts: BusinessClaims,
    brief: CreativeBrief,
    storyboard: StoryboardInput,
) -> PreproductionValidationResponse:
    """Evaluate only deterministic checks supported by the frontend rule source.

    Inputs must already pass the strict contract schemas. This function performs
    no I/O and treats review status and confirmation as caller-submitted signals.
    """
    findings: list[PreproductionFinding] = []
    fact_values = facts.facts
    scenes = storyboard.scenes
    approved_facts = [fact for fact in fact_values if fact.status == "approved"]
    eligible_fact_ids = [fact.id for fact in approved_facts]

    if not brief.requirementsConfirmed:
        findings.append(_finding(
            "brief.confirmation.required", "blocker", "brief",
            "Brief needs human confirmation",
            "The submitted brief has not been explicitly confirmed as reviewed by a person.",
            "Review the brief before setting its confirmation signal. Confirmation does not verify business facts.",
            [_BRIEF_ROUTE], True,
        ))

    if not approved_facts:
        findings.append(_finding(
            "facts.none-approved", "warning", "facts",
            "No facts are marked approved",
            "The submitted review states contain no facts marked approved for this limited claim review.",
            "Review relevant facts. Approval remains caller-supplied and does not independently verify or authorize a claim.",
            [_REVIEW_ROUTE], False,
        ))

    for fact in fact_values:
        if fact.status == "unreviewed":
            findings.append(_finding(
                f"facts.unreviewed.{fact.id}", "warning", "facts",
                f"Review the unreviewed {fact.category.lower()} fact",
                f"“{fact.claim}” is marked unreviewed in the submitted data and is not eligible as approved content.",
                "Review this fact or remove any unsupported use from the storyboard.",
                [_REVIEW_ROUTE], False, fact_id=fact.id,
            ))
        elif fact.status == "rejected":
            findings.append(_finding(
                f"facts.rejected.{fact.id}", "warning", "facts",
                f"Remove or revisit the rejected {fact.category.lower()} fact",
                f"“{fact.claim}” is marked rejected in the submitted data and is excluded from approved content.",
                "Do not use this claim in creative copy; revisit it in Fact Review or remove it from creative text.",
                [_REVIEW_ROUTE], False, fact_id=fact.id,
            ))

    if not scenes:
        findings.append(_finding(
            "storyboard.empty", "blocker", "storyboard",
            "Storyboard is empty",
            "There are no scenes from which to plan or preview a sequence.",
            "Add at least one illustrative scene in the Storyboard.",
            [_STORYBOARD_ROUTE], True,
        ))

    any_previewable_content = any(
        _nonempty(scene.visualDirection)
        or _nonempty(scene.onScreenText)
        or _nonempty(scene.narration)
        for scene in scenes
    )
    if scenes and not any_previewable_content:
        findings.append(_finding(
            "storyboard.no-usable-content", "blocker", "storyboard",
            "Storyboard has no usable scene content",
            "No scene contains visual direction, on-screen text, or narration to communicate a previewable idea.",
            "Add visual direction or intentional scene copy in the Storyboard.",
            [_STORYBOARD_ROUTE], True,
        ))

    for scene in scenes:
        if any_previewable_content and not _nonempty(scene.visualDirection):
            findings.append(_finding(
                f"storyboard.visual-direction-missing.{scene.id}", "blocker", "storyboard",
                "Visual direction is missing",
                f"Scene “{scene.title}” has no visual direction.",
                "Describe an illustrative visual approach or remove the scene.",
                [_STORYBOARD_ROUTE], True, scene_id=scene.id,
            ))
        if not _nonempty(scene.narrativePurpose):
            findings.append(_finding(
                f"storyboard.purpose-missing.{scene.id}", "blocker", "storyboard",
                "Scene narrative purpose is missing",
                f"Scene “{scene.title}” does not explain its role in the sequence.",
                "Describe what this scene is intended to communicate.",
                [_STORYBOARD_ROUTE], True, scene_id=scene.id,
            ))

    planned_runtime = calculate_storyboard_runtime(scenes)
    target_runtime = brief.duration
    runtime_difference = planned_runtime - target_runtime if planned_runtime is not None else None
    runtime_unavailable_reason: Literal["empty"] | None = "empty" if not scenes else None
    if runtime_difference is not None and runtime_difference != 0:
        difference = abs(runtime_difference)
        relation = "longer" if runtime_difference > 0 else "shorter"
        findings.append(_finding(
            "runtime.target-mismatch", "warning", "runtime",
            "Resolve the runtime mismatch",
            f"The planned sequence is {difference} {'second' if difference == 1 else 'seconds'} {relation} than the {target_runtime}-second brief target.",
            "Review the target in the Creative Brief or edit scene durations. No values are changed automatically.",
            [_STORYBOARD_ROUTE, _BRIEF_ROUTE], False,
        ))

    facts_by_normalized_claim: dict[str, list[BusinessClaim]] = {}
    for fact in fact_values:
        facts_by_normalized_claim.setdefault(_normalize_claim(fact.claim), []).append(fact)

    for scene in scenes:
        matched: dict[str, tuple[BusinessClaim, list[str]]] = {}
        for channel, text in (("on-screen text", scene.onScreenText), ("narration", scene.narration)):
            if not _nonempty(text):
                continue
            for fact in facts_by_normalized_claim.get(_normalize_claim(text), []):
                if fact.id not in matched:
                    matched[fact.id] = (fact, [])
                matched[fact.id][1].append(channel)

        for fact, channels in matched.values():
            approved = fact.status == "approved"
            status_text = (
                "marked approved in the caller-supplied review state"
                if approved
                else "marked rejected and excluded from caller-marked approved content"
                if fact.status == "rejected"
                else "marked unreviewed and not eligible as caller-marked approved content"
            )
            findings.append(_finding(
                f"grounding.exact-match.{scene.id}.{fact.id}",
                "info" if approved else "warning",
                "grounding",
                "Scene copy matches a caller-marked approved fact" if approved else "Scene copy matches an unsupported fact",
                f"The {' and '.join(channels)} in scene “{scene.title}” exactly matches “{fact.claim}”, which is {status_text}. This match does not establish truth.",
                "Do not treat this match or caller-supplied approval as independent verification."
                if approved
                else "Review or remove this claim in the Storyboard and resolve the fact status in Fact Review.",
                [_STORYBOARD_ROUTE, _REVIEW_ROUTE], False,
                fact_id=fact.id, scene_id=scene.id,
            ))

    findings.append(_finding(
        "grounding.exact-match-limitations", "info", "grounding",
        "Claim matching is intentionally limited",
        "Only exact text matches after lowercase conversion and whitespace normalization are associated with facts. Unmatched copy and paraphrases are not analyzed and are not thereby verified or safe.",
        "Manually review all creative text against source evidence; this endpoint does not independently verify supplied sources.",
        [_STORYBOARD_ROUTE, _REVIEW_ROUTE], False,
    ))
    findings.append(_finding(
        "production.checks-unavailable", "info", "production",
        "Additional production checks are not evaluated",
        "This deterministic evaluation does not independently verify sources or claims, analyze semantic meaning, assess legal or advertising policy, persist data, or generate media.",
        "Treat this result as planning support only; human review remains necessary.",
        [_READINESS_ROUTE], False,
    ))

    severity_order = _SEVERITIES
    unique_findings = list({finding.id: finding for finding in findings}.values())
    unique_findings.sort(key=lambda finding: (
        severity_order[finding.severity],
        _CATEGORIES.index(finding.category),
        finding.affectedFactId or finding.affectedSceneId or finding.id,
        finding.id,
    ))
    blocker_count = sum(finding.blocksReadiness for finding in unique_findings)
    warning_count = sum(finding.severity == "warning" for finding in unique_findings)
    info_count = sum(finding.severity == "info" for finding in unique_findings)

    return PreproductionValidationResponse(
        requestSchemaValid=True,
        evaluationStatus="evaluated-with-limitations",
        readinessStatus="needs-attention" if blocker_count else "ready-for-human-review",
        briefConfirmationSignal="caller-declared-confirmed" if brief.requirementsConfirmed else "not-confirmed",
        factualVerification="not-performed",
        findings=unique_findings,
        summary=FindingSummary(
            blockerCount=blocker_count,
            warningCount=warning_count,
            infoCount=info_count,
        ),
        factSummary=FactSummary(
            total=len(fact_values),
            callerMarkedApproved=len(approved_facts),
            unreviewed=sum(fact.status == "unreviewed" for fact in fact_values),
            rejected=sum(fact.status == "rejected" for fact in fact_values),
            invalidStatus=0,
            eligibleFactIds=eligible_fact_ids,
        ),
        storyboardSummary=StoryboardSummary(
            sceneCount=len(scenes),
            plannedRuntimeSeconds=planned_runtime,
            targetRuntimeSeconds=target_runtime,
            runtimeDifferenceSeconds=runtime_difference,
            runtimeUnavailableReason=runtime_unavailable_reason,
        ),
    )
