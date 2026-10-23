import type { Metadata } from "next";
import Link from "next/link";
import { northstarDemoProject } from "./review/demo-facts";
import "./sample-project.css";

export const metadata: Metadata = {
  title: "Northstar Coffee sample — Spotloom Studio",
  description: "An illustrative read-only sample project in Spotloom Studio.",
};

export default function NorthstarSamplePage() {
  return (
    <div className="sample-detail">
      <Link className="sample-back-link" href="/#overview">← Back to Overview</Link>
      <header className="sample-detail-heading">
        <p className="workspace-kicker">Sample project <span aria-hidden="true">·</span> Illustrative data</p>
        <h1>Northstar <em>Coffee</em></h1>
        <p className="sample-detail-summary">A read-only example showing how business context could be organized before creative work begins.</p>
      </header>

      <section className="sample-notice" aria-label="Sample data notice">
        <span className="sample-notice-mark" aria-hidden="true">i</span>
        <p><strong>Demonstration only.</strong> No website was scanned, no business claims were verified, and nothing was saved. Every item below is illustrative.</p>
      </section>

      <section className="sample-facts" aria-labelledby="sample-facts-title">
        <div className="sample-facts-heading">
          <div><p className="workspace-label">Business snapshot</p><h2 id="sample-facts-title">A little context, clearly marked.</h2></div>
          <span>READ ONLY</span>
        </div>
        <dl>
          {northstarDemoProject.facts.map((fact) => (
            <div className="sample-fact-row" key={fact.id}>
              <dt>{fact.category}</dt>
              <dd>{fact.claim}</dd>
              <span className="illustrative-tag">Illustrative</span>
            </div>
          ))}
        </dl>
      </section>

      <footer className="sample-detail-footer">
        <p>This sample does not represent extracted or verified business information.</p>
        <div className="sample-detail-actions">
          <Link className="sample-review-action" href="/projects/sample-northstar/review">View illustrative fact review <span aria-hidden="true">↗</span></Link>
          <Link className="sample-review-action" href="/projects/sample-northstar/brief">Build a creative brief <span aria-hidden="true">↗</span></Link>
          <Link className="sample-review-action" href="/projects/sample-northstar/storyboard">Plan storyboard scenes <span aria-hidden="true">↗</span></Link>
          <Link className="sample-return-action" href="/#overview">Return to Overview <span aria-hidden="true">↗</span></Link>
        </div>
      </footer>
    </div>
  );
}
