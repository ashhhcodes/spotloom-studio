"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useNorthstarProjectState } from "../demo-project-provider";
import {
  validateNorthstarPreproduction,
  type FindingCategory,
  type FindingSeverity,
  type WorkspaceRoute,
} from "../preproduction-validation";

const categoryLabels: Record<FindingCategory, string> = {
  brief: "Creative brief",
  facts: "Business facts",
  storyboard: "Storyboard",
  runtime: "Runtime",
  grounding: "Claim grounding",
  production: "Production boundary",
};

const severityLabels: Record<FindingSeverity, string> = {
  blocker: "Blocker",
  warning: "Warning",
  info: "Information",
};

const routeLabels: Record<WorkspaceRoute, string> = {
  "/projects/sample-northstar/brief": "Open Creative Brief",
  "/projects/sample-northstar/review": "Open Fact Review",
  "/projects/sample-northstar/storyboard": "Edit Storyboard",
  "/projects/sample-northstar/creative": "View Creative Readiness",
};

const categoryOrder: FindingCategory[] = ["brief", "facts", "storyboard", "runtime", "grounding", "production"];

function runtimeText(value: number | null, reason: string | null) {
  if (value !== null) return `${value} sec`;
  if (reason === "empty") return "Unavailable — no scenes";
  if (reason === "invalid-scene-duration") return "Unavailable — check scene durations";
  if (reason === "invalid-target") return "Unavailable — check brief target";
  return "Unavailable";
}

export default function CreativeReadinessWorkspace() {
  const { facts, brief, scenes } = useNorthstarProjectState();
  const result = useMemo(() => validateNorthstarPreproduction(facts, brief, scenes), [facts, brief, scenes]);
  const statusLabel = result.status === "needs-attention" ? "Needs attention" : "Ready for human review";
  const groups = categoryOrder
    .map((category) => ({ category, findings: result.findings.filter((finding) => finding.category === category) }))
    .filter((group) => group.findings.length > 0);

  return (
    <div className="creative-readiness-page">
      <nav className="readiness-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link href="/#overview">Overview</Link></li>
          <li><Link href="/projects/sample-northstar">Northstar Coffee sample</Link></li>
          <li aria-current="page">Creative readiness</li>
        </ol>
      </nav>

      <header className="readiness-heading">
        <p className="readiness-kicker">Northstar Coffee <span aria-hidden="true">/</span> Local pre-production check</p>
        <h1>Review before<br /><em>production.</em></h1>
        <p>Check the current illustrative brief, reviewed facts, and storyboard together. This deterministic check explains issues; it does not generate an advertisement.</p>
      </header>

      <aside className="readiness-demo-notice" aria-labelledby="readiness-demo-title">
        <span aria-hidden="true">i</span>
        <div><h2 id="readiness-demo-title">Demo only · temporary shared state</h2><p>Content is illustrative. Changes to facts, brief, and scenes are shared across Northstar pages in this tab and reset on refresh. No data is sent to a backend.</p></div>
      </aside>

      <section className="preflight-overview" aria-labelledby="preflight-overview-title" aria-live="polite">
        <div className={`preflight-verdict preflight-${result.status}`}>
          <p className="readiness-kicker">Derived structural status <span className="preflight-demo-tag">DEMO ONLY</span></p>
          <h2 id="preflight-overview-title">{statusLabel}</h2>
          <p>{result.status === "needs-attention"
            ? "Resolve the blockers below before marking this illustrative project ready for human review."
            : "Local structural checks pass and the current demo brief was confirmed. Warnings and production limitations still apply."}</p>
          <small>Human-review readiness is not factual verification or approval to publish.</small>
        </div>
        <ul className="preflight-finding-counts" aria-label="Finding counts">
          <li className="preflight-count-blocker"><strong>{result.blockerCount}</strong><span>Blockers</span></li>
          <li className="preflight-count-warning"><strong>{result.warningCount}</strong><span>Warnings</span></li>
          <li className="preflight-count-info"><strong>{result.infoCount}</strong><span>Information</span></li>
        </ul>
      </section>

      <section className="preflight-metrics" aria-label="Current project summary">
        <div><span>Business facts</span><strong>{result.factSummary.total} total</strong><small>{result.factSummary.approved} approved · {result.factSummary.unreviewed} unreviewed · {result.factSummary.rejected} rejected{result.factSummary.invalidStatus > 0 ? ` · ${result.factSummary.invalidStatus} invalid status` : ""}</small></div>
        <div><span>Approved for demo</span><strong>{result.factSummary.eligibleFacts.length}</strong><small>Not independently verified</small></div>
        <div><span>Storyboard scenes</span><strong>{result.storyboardSummary.sceneCount}</strong><small>Current ordered scene list</small></div>
        <div><span>Planned runtime</span><strong>{runtimeText(result.storyboardSummary.plannedRuntimeSeconds, result.storyboardSummary.runtimeUnavailableReason)}</strong><small>{result.storyboardSummary.runtimeDifferenceSeconds === null ? "Compared with brief target below" : result.storyboardSummary.runtimeDifferenceSeconds === 0 ? "Matches the brief target" : `${Math.abs(result.storyboardSummary.runtimeDifferenceSeconds)} sec ${result.storyboardSummary.runtimeDifferenceSeconds > 0 ? "over" : "under"} target`}</small></div>
        <div><span>Brief target</span><strong>{result.storyboardSummary.targetRuntimeSeconds === null ? "Invalid or missing" : `${result.storyboardSummary.targetRuntimeSeconds} sec`}</strong><small>Aspect ratio: {typeof brief.aspectRatio === "string" ? brief.aspectRatio : "Invalid or missing"}</small></div>
      </section>

      <section className="preflight-findings" aria-labelledby="preflight-findings-title">
        <div className="readiness-section-heading"><div><p className="readiness-kicker">Current shared state</p><h2 id="preflight-findings-title">Findings and next steps</h2></div><p>Re-evaluated from the brief, facts, and ordered scenes</p></div>
        {groups.map(({ category, findings }) => (
          <section className="preflight-category" key={category} aria-labelledby={`preflight-category-${category}`}>
            <h3 id={`preflight-category-${category}`}>{categoryLabels[category]}</h3>
            <ul>
              {findings.map((finding) => (
                <li className={`preflight-finding preflight-finding-${finding.severity}`} key={finding.id}>
                  <article>
                    <div className="preflight-finding-heading"><span className={`preflight-severity preflight-severity-${finding.severity}`}>{severityLabels[finding.severity]}</span><h4>{finding.title}</h4></div>
                    <p>{finding.explanation}</p>
                    <p className="preflight-resolution"><strong>Suggested action:</strong> {finding.resolution}</p>
                    <div className="preflight-destinations">{finding.destinationRoutes.map((route) => <Link href={route} key={route}>{routeLabels[route]} <span aria-hidden="true">↗</span></Link>)}</div>
                  </article>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </section>

      <section className="readiness-next-step" aria-labelledby="readiness-next-title">
        <div><p className="readiness-kicker">Generation unavailable</p><h2 id="readiness-next-title">A review result does not create an ad.</h2><p>AI semantic analysis, legal and advertising-policy checks, real media generation, and backend integration are not implemented. Passing these local checks does not establish accuracy or publication safety.</p></div>
        <div className="readiness-next-actions"><button type="button" disabled aria-describedby="readiness-disabled-note">Generate Ad <span aria-hidden="true">↗</span></button><p id="readiness-disabled-note">Unavailable in this frontend-only demo. No script, video, or advertisement will be generated.</p><nav className="readiness-action-links" aria-label="Northstar project workspaces"><Link href="/projects/sample-northstar/brief">Review the creative brief</Link><Link href="/projects/sample-northstar/storyboard">Edit storyboard scenes</Link><Link href="/projects/sample-northstar/review">Review business facts</Link><Link href="/projects/sample-northstar/package">Preview production package</Link></nav></div>
      </section>

      <footer className="readiness-footer"><p>Demo only · Local deterministic checks · No independently validated source evidence</p><Link href="/projects/sample-northstar">Northstar sample project</Link></footer>
    </div>
  );
}
