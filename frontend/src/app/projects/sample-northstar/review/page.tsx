import type { Metadata } from "next";
import Link from "next/link";
import FactReviewWorkspace from "./fact-review-workspace";
import "./review.css";

export const metadata: Metadata = {
  title: "Review business facts — Northstar Coffee demo — Spotloom Studio",
  description: "A visual demonstration of business fact review using illustrative sample data.",
};

export default function NorthstarFactReviewPage() {
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

      <FactReviewWorkspace />

      <footer className="review-footer">
        <p>Demo only · No business information has been verified or saved.</p>
        <Link href="/projects/sample-northstar">Return to Northstar Coffee sample <span aria-hidden="true">↗</span></Link>
      </footer>
    </div>
  );
}
