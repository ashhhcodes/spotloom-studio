import type { Metadata } from "next";
import Link from "next/link";
import "./review.css";

export const metadata: Metadata = {
  title: "Review business facts — Northstar Coffee demo — Spotloom Studio",
  description: "A visual demonstration of business fact review using illustrative sample data.",
};

type ReviewStatus = "Unreviewed" | "Approved" | "Rejected";

const demoFacts: { category: string; claim: string; status: ReviewStatus }[] = [
  { category: "Product", claim: "Small-batch roasted coffee", status: "Unreviewed" },
  { category: "Audience", claim: "People looking for a considered everyday cup", status: "Approved" },
  { category: "Possible message", claim: "A good cup, made simple.", status: "Rejected" },
];

const statusDetails: Record<ReviewStatus, { icon: string; className: string }> = {
  Unreviewed: { icon: "○", className: "status-unreviewed" },
  Approved: { icon: "✓", className: "status-approved" },
  Rejected: { icon: "×", className: "status-rejected" },
};

function FactCard({ category, claim, status }: (typeof demoFacts)[number]) {
  const statusDetail = statusDetails[status];

  return (
    <li className="review-item">
      <article className="review-fact">
        <div className="review-claim">
          <p className="review-field-label">Illustrative claim <span>·</span> {category}</p>
          <h3>{claim}</h3>
          <p className="review-demo-label">Sample content for layout demonstration</p>
        </div>
        <div className="review-source">
          <p className="review-field-label">Source reference</p>
          <details>
            <summary>Demo source details</summary>
            <dl>
              <div><dt>Reference</dt><dd>Demo source — no website scanned</dd></div>
              <div><dt>Page or section</dt><dd>Placeholder — no page inspected</dd></div>
              <div><dt>Excerpt</dt><dd>None — no evidence collected</dd></div>
            </dl>
          </details>
          <p className="review-source-placeholder">No extracted evidence is associated with this illustrative claim.</p>
        </div>
        <div className="review-status">
          <p className="review-field-label">Review status</p>
          <span className={`review-status-label ${statusDetail.className}`}>
            <span aria-hidden="true">{statusDetail.icon}</span> {status}
          </span>
        </div>
      </article>
    </li>
  );
}

export default function NorthstarFactReviewPage() {
  const statusCounts = demoFacts.reduce<Record<ReviewStatus, number>>(
    (counts, fact) => ({ ...counts, [fact.status]: counts[fact.status] + 1 }),
    { Unreviewed: 0, Approved: 0, Rejected: 0 },
  );

  return (
    <div className="fact-review-page">
      <nav className="review-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link href="/#overview">Overview</Link></li>
          <li><Link href="/projects/sample-northstar">Northstar Coffee sample</Link></li>
          <li aria-current="page">Fact review</li>
        </ol>
      </nav>

      <header className="fact-review-heading">
        <p className="review-kicker">Northstar Coffee <span aria-hidden="true">/</span> Sample project</p>
        <h1>Review the facts<br />before they <em>shape the work.</em></h1>
        <p>Business claims need a clear source and a deliberate review before they can inform generated creative.</p>
      </header>

      <aside className="review-demo-notice" aria-labelledby="demo-notice-title">
        <span className="review-notice-icon" aria-hidden="true">i</span>
        <div><h2 id="demo-notice-title">Illustrative demo data</h2><p>These Northstar Coffee claims and statuses are examples only. No website was scanned, no evidence was collected, and no facts were verified.</p></div>
      </aside>

      <section className="review-overview" aria-label="Illustrative review summary">
        <div className="review-overview-title"><p className="review-kicker">Demo set</p><h2>Three illustrative facts</h2></div>
        <ul className="review-counts">
          {(Object.keys(statusCounts) as ReviewStatus[]).map((status) => {
            const statusDetail = statusDetails[status];
            return <li className={statusDetail.className} key={status}><span aria-hidden="true">{statusDetail.icon}</span> {statusCounts[status]} {status.toLowerCase()}</li>;
          })}
        </ul>
      </section>

      <section className="review-facts-section" aria-labelledby="facts-heading">
        <div className="review-facts-heading"><div><p className="review-kicker">Business context</p><h2 id="facts-heading">Claims and their sources</h2></div><p>All content shown is illustrative</p></div>
        <ul className="review-facts-list">
          {demoFacts.map((fact) => <FactCard key={fact.category} {...fact} />)}
        </ul>
      </section>

      <section className="review-next-step" aria-labelledby="next-step-heading">
        <div><p className="review-kicker">What comes next</p><h2 id="next-step-heading">Reviewed facts can guide creative work.</h2><p>In the complete workflow, only reviewed and approved claims will be available to use in generated creative.</p></div>
        <div className="review-next-control"><button type="button" disabled aria-describedby="next-step-note">Continue to creative work <span aria-hidden="true">↗</span></button><p id="next-step-note">Unavailable in this visual demo. Review actions and creative generation are not implemented here.</p></div>
      </section>

      <footer className="review-footer">
        <p>Demo only · No business information has been verified or saved.</p>
        <Link href="/projects/sample-northstar">Return to Northstar Coffee sample <span aria-hidden="true">↗</span></Link>
      </footer>
    </div>
  );
}
