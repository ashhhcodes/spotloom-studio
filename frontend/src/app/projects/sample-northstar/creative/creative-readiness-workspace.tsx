"use client";

import Link from "next/link";
import { deriveReviewStatusCounts, getApprovedDemoFacts, northstarDemoProject, type ReviewStatus } from "../review/demo-facts";
import { useNorthstarProjectState } from "../demo-project-provider";

const statusDetails: Record<ReviewStatus, { icon: string; className: string; label: string }> = {
  unreviewed: { icon: "○", className: "readiness-unreviewed", label: "Unreviewed" },
  approved: { icon: "✓", className: "readiness-approved", label: "Approved" },
  rejected: { icon: "×", className: "readiness-rejected", label: "Rejected" },
};

const statusOrder: ReviewStatus[] = ["unreviewed", "approved", "rejected"];

const blockers = [
  { title: "Real source extraction", description: "No Northstar website has been scanned. The facts shown here are sample copy only." },
  { title: "Evidence review", description: "There are no source URLs, page references, or excerpts to check against the claims." },
  { title: "Persistence and backend", description: "Review decisions are held in page memory and reset. No connected service can validate or provide approved facts to a creative workflow." },
];

export default function CreativeReadinessWorkspace() {
  const { facts } = useNorthstarProjectState();
  const counts = deriveReviewStatusCounts(facts);
  const approvedFacts = getApprovedDemoFacts(facts);

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
        <p className="readiness-kicker">{northstarDemoProject.name} <span aria-hidden="true">/</span> Illustrative sample</p>
        <h1>Ready for creative?<br /><em>Not yet.</em></h1>
        <p>This sample has a starting review snapshot, but no real business facts or evidence. It cannot authorize an advertisement.</p>
      </header>

      <aside className="readiness-demo-notice" aria-labelledby="readiness-demo-title">
        <span aria-hidden="true">i</span>
        <div><h2 id="readiness-demo-title">Illustrative readiness snapshot</h2><p>Review changes are shared across Northstar sample pages in this tab only. They are held in memory and reset when the page is refreshed. Demo approval does not mean a claim is verified for real-world use.</p></div>
      </aside>

      <section className="readiness-summary" aria-labelledby="readiness-summary-title">
        <div className="readiness-summary-copy">
          <p className="readiness-kicker">Current sample review</p>
          <h2 id="readiness-summary-title" aria-live="polite">{approvedFacts.length} of {facts.length} facts marked approved for this demo</h2>
          <p>“Approved” here describes only the illustrative sample state. It does not mean a claim is verified or approved for real advertising.</p>
          <ul className="readiness-counts" aria-label="Current sample fact counts">
            {statusOrder.map((status) => {
              const detail = statusDetails[status];
              return <li className={detail.className} key={status}><span aria-hidden="true">{detail.icon}</span>{counts[status]} {detail.label.toLowerCase()}</li>;
            })}
          </ul>
        </div>
        <p className="readiness-verdict"><span aria-hidden="true">×</span><strong>Not ready for real creative</strong><small>{blockers.length} prerequisites remain</small></p>
      </section>

      <section className="readiness-facts" aria-labelledby="readiness-facts-title">
        <div className="readiness-section-heading"><div><p className="readiness-kicker">Business context</p><h2 id="readiness-facts-title">What the sample review says</h2></div><p>Illustrative claims only · no evidence collected</p></div>
        <ul>
          {facts.map((fact) => {
            const detail = statusDetails[fact.status];
            return <li className="readiness-fact" key={fact.id}><div><p className="readiness-fact-category">{fact.category} <span>·</span> Demo claim</p><h3>{fact.claim}</h3></div><span className={`readiness-status ${detail.className}`}><span aria-hidden="true">{detail.icon}</span>{detail.label}</span><p className="readiness-use-note">{fact.status === "approved" ? "Eligible for demo copy only; not verified for real-world use." : fact.status === "rejected" ? "Rejected sample claim. It must not be used in creative copy." : "Unreviewed sample claim. It is not available for creative use."}</p></li>;
          })}
        </ul>
        <div className="readiness-eligible" aria-live="polite">
          <h3>Claims eligible for demo copy</h3>
          {approvedFacts.length > 0
            ? <ul>{approvedFacts.map((fact) => <li key={fact.id}>{fact.claim}</li>)}</ul>
            : <p>No facts are approved in the current demo state.</p>}
          <p>Demo eligibility is temporary and does not authorize real advertising.</p>
        </div>
      </section>

      <section className="readiness-blockers" aria-labelledby="readiness-blockers-title">
        <div className="readiness-section-heading"><div><p className="readiness-kicker">Before any real creative</p><h2 id="readiness-blockers-title">Resolve these blockers first</h2></div><p>Required for a trustworthy workflow</p></div>
        <ol>{blockers.map((blocker, index) => <li key={blocker.title}><span className="readiness-blocker-number">0{index + 1}</span><div><h3>{blocker.title}</h3><p>{blocker.description}</p></div><span className="readiness-blocker-state"><span aria-hidden="true">×</span> Missing</span></li>)}</ol>
      </section>

      <section className="readiness-next-step" aria-labelledby="readiness-next-title">
        <div><p className="readiness-kicker">Generation unavailable</p><h2 id="readiness-next-title">No advertisement can be generated from this sample.</h2><p>The creative editor, real source evidence, and backend persistence are not implemented. Nothing on this page sends data or starts generation.</p></div>
        <div className="readiness-next-actions"><button type="button" disabled aria-describedby="readiness-disabled-note">Create an advertisement <span aria-hidden="true">↗</span></button><p id="readiness-disabled-note">Unavailable until real facts can be sourced, reviewed, and supplied to an implemented workflow.</p><Link href="/projects/sample-northstar/review">Return to fact review <span aria-hidden="true">←</span></Link></div>
      </section>

      <footer className="readiness-footer"><p>Demo only · No claims were extracted, verified, or saved.</p><Link href="/projects/sample-northstar">Northstar sample project</Link></footer>
    </div>
  );
}
