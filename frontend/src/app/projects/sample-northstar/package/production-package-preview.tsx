"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useNorthstarProjectState } from "../demo-project-provider";
import { getApprovedDemoFacts } from "../review/demo-facts";
import ProductionPackagePreflight from "./production-package-preflight";
import {
  validateNorthstarPreproduction,
  type FindingSeverity,
  type WorkspaceRoute,
} from "../preproduction-validation";

const routeLabels: Record<WorkspaceRoute, string> = {
  "/projects/sample-northstar/brief": "Edit the creative brief",
  "/projects/sample-northstar/review": "Review business facts",
  "/projects/sample-northstar/storyboard": "Edit storyboard",
  "/projects/sample-northstar/creative": "Return to Creative Readiness",
};

const severityLabels: Record<FindingSeverity, string> = {
  blocker: "Blocker",
  warning: "Warning",
  info: "Information",
};

const objectiveLabels = {
  awareness: "Awareness",
  engagement: "Engagement",
  traffic: "Traffic",
  conversions: "Conversions",
} as const;

const platformLabels = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  other: "Other",
} as const;

function displayValue(value: string) {
  return value.trim() || "Not supplied";
}

function plannedRuntimeText(value: number | null, reason: string | null) {
  if (value !== null) return `${value} seconds`;
  if (reason === "empty") return "Unavailable — the storyboard has no scenes.";
  if (reason === "invalid-scene-duration") return "Unavailable — one or more scene durations are invalid.";
  if (reason === "invalid-target") return "Unavailable — the brief target duration is invalid.";
  return "Unavailable — runtime could not be calculated.";
}

export default function ProductionPackagePreview() {
  const { facts, brief, scenes } = useNorthstarProjectState();
  const validation = useMemo(
    () => validateNorthstarPreproduction(facts, brief, scenes),
    [facts, brief, scenes],
  );
  const approvedFacts = getApprovedDemoFacts(facts);
  const statusLabel = validation.status === "needs-attention"
    ? "Needs attention"
    : "Ready for human review";
  const runtimeDifference = validation.storyboardSummary.runtimeDifferenceSeconds;

  return (
    <div className="package-page">
      <nav className="package-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link href="/#overview">Overview</Link></li>
          <li><Link href="/projects/sample-northstar">Northstar Coffee sample</Link></li>
          <li aria-current="page">Production package preview</li>
        </ol>
      </nav>

      <header className="package-heading">
        <p className="package-kicker">Northstar Coffee <span aria-hidden="true">/</span> Sample project</p>
        <div className="package-title-row">
          <h1>Production package<br /><em>preview.</em></h1>
          <span className="package-demo-badge">DEMO ONLY</span>
        </div>
        <p>This read-only view brings the current creative plan together for review. It is not an exported production package or a generated advertisement.</p>
      </header>

      <aside className="package-notice" aria-labelledby="package-notice-title">
        <span aria-hidden="true">i</span>
        <div>
          <h2 id="package-notice-title">Illustrative plan · temporary shared state</h2>
          <p>Changes are shared across Northstar project pages in this tab and reset on refresh. Preview data is not submitted automatically; only JSON explicitly submitted in the preflight below is sent to the configured backend. No video, audio, images, or finished advertisement have been generated.</p>
        </div>
      </aside>

      <ProductionPackagePreflight />

      <section className="package-section package-brief" aria-labelledby="package-brief-title">
        <div className="package-section-heading">
          <div><p className="package-kicker">01 · Campaign direction</p><h2 id="package-brief-title">Creative brief</h2></div>
          <Link className="package-text-link" href="/projects/sample-northstar/brief">Edit the brief <span aria-hidden="true">↗</span></Link>
        </div>

        {!brief.requirementsConfirmed && (
          <p className="package-confirmation-notice"><strong>Brief not confirmed.</strong> Review the illustrative defaults and confirm the brief before human review. <Link href="/projects/sample-northstar/brief">Open the brief</Link></p>
        )}
        {brief.requirementsConfirmed && (
          <p className="package-confirmation package-confirmation-done"><span aria-hidden="true">✓</span> Confirmed for this demo’s human review · not factual verification</p>
        )}

        <dl className="package-brief-grid">
          <div><dt>Campaign objective</dt><dd>{objectiveLabels[brief.objective] ?? "Not supplied"}</dd></div>
          <div><dt>Target audience</dt><dd>{displayValue(brief.targetAudience)}</dd></div>
          <div><dt>Product or offer</dt><dd>{displayValue(brief.productOrOffer)}</dd></div>
          <div><dt>Key message</dt><dd>{displayValue(brief.keyMessage)}</dd></div>
          <div><dt>Value proposition</dt><dd>{displayValue(brief.valueProposition)}</dd></div>
          <div><dt>Platform</dt><dd>{platformLabels[brief.platform] ?? "Not supplied"}</dd></div>
          <div><dt>Aspect ratio</dt><dd>{brief.aspectRatio || "Not supplied"}</dd></div>
          <div><dt>Target duration</dt><dd>{brief.duration ? `${brief.duration} seconds` : "Not supplied"}</dd></div>
          <div><dt>Tone and creative direction</dt><dd>{displayValue(brief.tone)}</dd></div>
          <div><dt>Call to action</dt><dd>{displayValue(brief.callToAction)}</dd></div>
        </dl>
        <p className="package-field-note">These values began as illustrative demo defaults. Populated fields do not imply that campaign requirements were supplied.</p>
      </section>

      <section className="package-section" aria-labelledby="package-storyboard-title">
        <div className="package-section-heading">
          <div><p className="package-kicker">02 · Ordered sequence</p><h2 id="package-storyboard-title">Storyboard</h2></div>
          <Link className="package-text-link" href="/projects/sample-northstar/storyboard">Edit scenes <span aria-hidden="true">↗</span></Link>
        </div>
        {scenes.length > 0 ? (
          <ol className="package-scenes">
            {scenes.map((scene, index) => {
              const sceneFindings = validation.findings.filter((finding) => finding.affectedSceneId === scene.id && finding.severity === "blocker");
              const invalidDuration = validation.findings.some((finding) => finding.id === `storyboard.duration-invalid.${scene.id}`);
              const titleMissing = !scene.title.trim();
              const purposeMissing = !scene.narrativePurpose.trim();
              const visualMissing = !scene.visualDirection.trim();
              return (
                <li className="package-scene" key={scene.id}>
                  <article>
                    <header className="package-scene-heading">
                      <div><p className="package-scene-number">SCENE {String(index + 1).padStart(2, "0")}</p><h3>{titleMissing ? <span className="package-missing">Untitled scene</span> : scene.title}</h3></div>
                      <span className="package-scene-duration">{invalidDuration ? "Invalid duration" : `${scene.durationSeconds} sec`}</span>
                    </header>
                    <dl className="package-scene-fields">
                      <div><dt>Narrative purpose</dt><dd>{purposeMissing ? <span className="package-missing">Not supplied</span> : scene.narrativePurpose}</dd></div>
                      <div><dt>Visual direction</dt><dd>{visualMissing ? <span className="package-missing">Not supplied</span> : scene.visualDirection}</dd></div>
                      <div><dt>On-screen text</dt><dd>{displayValue(scene.onScreenText)}</dd></div>
                      <div><dt>Narration</dt><dd>{displayValue(scene.narration)}</dd></div>
                      <div><dt>Transition or editing note</dt><dd>{displayValue(scene.transitionNote)}</dd></div>
                    </dl>
                    {sceneFindings.length > 0 && (
                      <p className="package-scene-warning">This scene has {sceneFindings.length} structural {sceneFindings.length === 1 ? "issue" : "issues"}. <Link href="/projects/sample-northstar/storyboard">Review it in the storyboard editor</Link>.</p>
                    )}
                  </article>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="package-empty">No scenes are currently in the storyboard. <Link href="/projects/sample-northstar/storyboard">Add scenes in the storyboard editor</Link>.</p>
        )}
      </section>

      <section className="package-section" aria-labelledby="package-runtime-title">
        <div className="package-section-heading">
          <div><p className="package-kicker">03 · Timing</p><h2 id="package-runtime-title">Runtime summary</h2></div>
        </div>
        <dl className="package-runtime-grid">
          <div><dt>Scene count</dt><dd>{validation.storyboardSummary.sceneCount}</dd></div>
          <div><dt>Planned runtime</dt><dd>{plannedRuntimeText(validation.storyboardSummary.plannedRuntimeSeconds, validation.storyboardSummary.runtimeUnavailableReason)}</dd></div>
          <div><dt>Brief target</dt><dd>{validation.storyboardSummary.targetRuntimeSeconds === null ? "Unavailable — check the brief" : `${validation.storyboardSummary.targetRuntimeSeconds} seconds`}</dd></div>
          <div><dt>Difference</dt><dd>{runtimeDifference === null ? "Unavailable" : runtimeDifference === 0 ? "Matches target" : `${Math.abs(runtimeDifference)} seconds ${runtimeDifference > 0 ? "over" : "under"} target`}</dd></div>
        </dl>
        <p className="package-field-note">Runtime is derived from valid current scene durations. No duration is changed automatically.</p>
      </section>

      <section className="package-section" aria-labelledby="package-claims-title">
        <div className="package-section-heading">
          <div><p className="package-kicker">04 · Reviewed context</p><h2 id="package-claims-title">Approved demo claims</h2></div>
          <Link className="package-text-link" href="/projects/sample-northstar/review">Open fact review <span aria-hidden="true">↗</span></Link>
        </div>
        <p className="package-section-intro">These claims are eligible for this demo workflow only. Approval is a review decision, not independent verification.</p>
        {approvedFacts.length > 0 ? (
          <ul className="package-claims">
            {approvedFacts.map((fact) => {
              const matches = validation.findings.filter((finding) => finding.category === "grounding" && finding.affectedFactId === fact.id && finding.affectedSceneId);
              return (
                <li className="package-claim" key={fact.id}>
                  <div className="package-claim-heading"><p className="package-claim-category">{fact.category}</p><span className="package-claim-status">✓ Approved for demo</span></div>
                  <p className="package-claim-text">{fact.claim}</p>
                  <dl className="package-source">
                    <div><dt>Source reference</dt><dd>{fact.source.reference}</dd></div>
                    <div><dt>Page or section</dt><dd>{fact.source.pageOrSection}</dd></div>
                    {fact.source.excerpt && <div><dt>Source excerpt</dt><dd>{fact.source.excerpt}</dd></div>}
                  </dl>
                  {matches.length > 0 && <div className="package-claim-matches"><h4>Limited exact-text matches</h4><ul>{matches.map((finding) => <li key={finding.id}>{finding.explanation}</li>)}</ul></div>}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="package-empty">No facts are currently approved for demo use. Unreviewed and rejected facts are excluded. <Link href="/projects/sample-northstar/review">Review the illustrative facts</Link>.</p>
        )}
        <p className="package-field-note">No source evidence has been collected for this sample. The validator only matches exact text after case and whitespace normalization; unmatched lines and paraphrases are not verified.</p>
      </section>

      <section className="package-section package-validation" aria-labelledby="package-validation-title" aria-live="polite">
        <div className="package-section-heading">
          <div><p className="package-kicker">05 · Local deterministic check</p><h2 id="package-validation-title">Validation and unresolved issues</h2></div>
          <Link className="package-text-link" href="/projects/sample-northstar/creative">Creative Readiness <span aria-hidden="true">↗</span></Link>
        </div>
        <div className="package-validation-summary">
          <div className={`package-status package-status-${validation.status}`}><span>Status</span><strong>{statusLabel}</strong><small>Demo only · not publication approval</small></div>
          <ul aria-label="Validation finding counts">
            <li><strong>{validation.blockerCount}</strong><span>Blockers</span></li>
            <li><strong>{validation.warningCount}</strong><span>Warnings</span></li>
            <li><strong>{validation.infoCount}</strong><span>Information</span></li>
          </ul>
        </div>
        {validation.findings.length > 0 ? (
          <ol className="package-findings">
            {validation.findings.map((finding) => (
              <li className={`package-finding package-finding-${finding.severity}`} key={finding.id}>
                <article>
                  <div className="package-finding-heading"><span>{severityLabels[finding.severity]}</span><h3>{finding.title}</h3></div>
                  <p>{finding.explanation}</p>
                  <p className="package-finding-resolution"><strong>Suggested action:</strong> {finding.resolution}</p>
                  <nav aria-label={`Destinations for ${finding.title}`} className="package-action-links">
                    {finding.destinationRoutes.map((route) => <Link href={route} key={route}>{routeLabels[route]}</Link>)}
                  </nav>
                </article>
              </li>
            ))}
          </ol>
        ) : (
          <p className="package-empty">No findings were returned by the local validation check.</p>
        )}
        {validation.status === "ready-for-human-review" && <p className="package-ready-note">The defined local structural checks passed. This does not mean the claims are verified, the plan is production-ready, or an advertisement is safe to publish.</p>}
      </section>

      <aside className="package-boundary" aria-labelledby="package-boundary-title">
        <p className="package-kicker">Production boundary</p>
        <h2 id="package-boundary-title">A plan is not a finished advertisement.</h2>
        <ul>
          <li>This is an illustrative demo package; business facts are not independently verified.</li>
          <li>Claim matching uses the validator’s limited exact-text rule; it does not semantically ground all narration or on-screen text.</li>
          <li>Legal review and advertising-policy compliance checks are not implemented.</li>
          <li>No video, audio, images, or finished advertisement have been generated.</li>
          <li>The illustrative preview data is not sent to a backend automatically.</li>
        </ul>
      </aside>

      <nav className="package-footer-actions" aria-label="Northstar project navigation">
        <Link href="/projects/sample-northstar/brief">Edit the creative brief</Link>
        <Link href="/projects/sample-northstar/storyboard">Edit storyboard</Link>
        <Link href="/projects/sample-northstar/review">Review business facts</Link>
        <Link href="/projects/sample-northstar/creative">Return to Creative Readiness</Link>
      </nav>
    </div>
  );
}
