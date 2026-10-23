import type { Metadata } from "next";
import Link from "next/link";
import { getApprovedDemoFacts, northstarDemoProject, type ReviewStatus } from "../review/demo-facts";
import "./creative.css";

export const metadata: Metadata = {
  title: "Creative readiness — Northstar Coffee demo — Spotloom Studio",
  description: "An illustrative readiness overview for the Northstar Coffee sample project.",
};

const statusDetails: Record<ReviewStatus, { icon: string; className: string }> = {
  unreviewed: { icon: "○", className: "readiness-unreviewed" },
  approved: { icon: "✓", className: "readiness-approved" },
  rejected: { icon: "×", className: "readiness-rejected" },
};
const statusLabels: Record<ReviewStatus, string> = { unreviewed: "Unreviewed", approved: "Approved", rejected: "Rejected" };

const blockers = [
  { title: "Real source extraction", description: "No Northstar website has been scanned. The facts shown here are sample copy only." },
  { title: "Evidence review", description: "There are no source URLs, page references, or excerpts to check against the claims." },
  { title: "Persistence and backend", description: "Review decisions are held in page memory and reset. No connected service can validate or provide approved facts to a creative workflow." },
];

export default function NorthstarCreativeReadinessPage() {
  const approvedCount = getApprovedDemoFacts(northstarDemoProject.facts).length;

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
        <div><h2 id="readiness-demo-title">Illustrative readiness snapshot</h2><p>This view uses the sample’s initial review statuses. Changes made on the fact-review route are temporary and are not shared here; this snapshot may reset when you navigate or refresh.</p></div>
      </aside>

      <section className="readiness-summary" aria-labelledby="readiness-summary-title">
        <div className="readiness-summary-copy">
          <p className="readiness-kicker">Current sample snapshot</p>
          <h2 id="readiness-summary-title">{approvedCount} of {northstarDemoProject.facts.length} facts marked approved for this demo</h2>
          <p>“Approved” here describes only the illustrative sample state. It does not mean a claim is verified or approved for real advertising.</p>
        </div>
        <p className="readiness-verdict"><span aria-hidden="true">×</span><strong>Not ready for real creative</strong><small>3 prerequisites remain</small></p>
      </section>

      <section className="readiness-facts" aria-labelledby="readiness-facts-title">
        <div className="readiness-section-heading"><div><p className="readiness-kicker">Business context</p><h2 id="readiness-facts-title">What the sample review says</h2></div><p>Illustrative claims only · no evidence collected</p></div>
        <ul>
          {northstarDemoProject.facts.map((fact) => {
            const detail = statusDetails[fact.status];
            return <li className="readiness-fact" key={fact.id}><div><p className="readiness-fact-category">{fact.category} <span>·</span> Demo claim</p><h3>{fact.claim}</h3></div><span className={`readiness-status ${detail.className}`}><span aria-hidden="true">{detail.icon}</span>{statusLabels[fact.status]}</span><p className="readiness-use-note">{fact.status === "approved" ? "Marked approved in the demo only; not verified for real-world use." : fact.status === "rejected" ? "Rejected sample claim. It must not be used in creative copy." : "Unreviewed sample claim. It is not available for creative use."}</p></li>;
          })}
        </ul>
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
