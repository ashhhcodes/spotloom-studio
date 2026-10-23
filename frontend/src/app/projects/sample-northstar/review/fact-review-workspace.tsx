"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { initialDemoFacts, type DemoFact, type ReviewStatus } from "./demo-facts";

const statuses: ReviewStatus[] = ["Unreviewed", "Approved", "Rejected"];
const statusDetails: Record<ReviewStatus, { icon: string; className: string }> = {
  Unreviewed: { icon: "○", className: "status-unreviewed" },
  Approved: { icon: "✓", className: "status-approved" },
  Rejected: { icon: "×", className: "status-rejected" },
};

export default function FactReviewWorkspace() {
  const [facts, setFacts] = useState(initialDemoFacts);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");

  const counts = facts.reduce<Record<ReviewStatus, number>>(
    (result, fact) => ({ ...result, [fact.status]: result[fact.status] + 1 }),
    { Unreviewed: 0, Approved: 0, Rejected: 0 },
  );
  const approvedCount = counts.Approved;

  function setStatus(fact: DemoFact, status: ReviewStatus) {
    setFacts((current) => current.map((item) => item.id === fact.id ? { ...item, status } : item));
    setAnnouncement(`${fact.category} marked ${status.toLowerCase()} in this demo. This change is temporary.`);
  }

  function beginEdit(fact: DemoFact) {
    setEditingId(fact.id);
    setDraft(fact.claim);
    setError("");
    setAnnouncement(`Editing ${fact.category} claim.`);
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft("");
    setError("");
    setAnnouncement("Correction canceled. The displayed claim is unchanged.");
  }

  function saveCorrection(event: FormEvent<HTMLFormElement>, fact: DemoFact) {
    event.preventDefault();
    const correctedClaim = draft.trim();
    if (!correctedClaim) {
      setError("Enter a claim before saving the correction.");
      return;
    }
    setFacts((current) => current.map((item) => item.id === fact.id
      ? { ...item, claim: correctedClaim, revisions: [...item.revisions, item.claim], status: "Unreviewed" }
      : item));
    setEditingId(null);
    setDraft("");
    setError("");
    setAnnouncement(`${fact.category} correction saved in this demo and returned to unreviewed. It is not saved after refresh.`);
  }

  return (
    <>
      <p className="review-persistence-note">Your review changes are temporary and will be lost when this page is refreshed.</p>

      <section className="review-overview" aria-label="Illustrative review summary" aria-live="polite" aria-atomic="true">
        <div className="review-overview-title"><p className="review-kicker">Demo set</p><h2>Three illustrative facts</h2></div>
        <ul className="review-counts">
          {statuses.map((status) => {
            const detail = statusDetails[status];
            return <li className={detail.className} key={status}><span aria-hidden="true">{detail.icon}</span> {counts[status]} {status.toLowerCase()}</li>;
          })}
        </ul>
      </section>

      <section className="review-facts-section" aria-labelledby="facts-heading">
        <div className="review-facts-heading"><div><p className="review-kicker">Business context</p><h2 id="facts-heading">Claims and their sources</h2></div><p>All content shown is illustrative</p></div>
        <ul className="review-facts-list">
          {facts.map((fact) => {
            const detail = statusDetails[fact.status];
            const isEditing = editingId === fact.id;
            return (
              <li className="review-item" key={fact.id}>
                <article className="review-fact">
                  <div className="review-claim">
                    <p className="review-field-label">Illustrative claim <span>·</span> {fact.category}</p>
                    {isEditing ? (
                      <form className="review-edit-form" onSubmit={(event) => saveCorrection(event, fact)}>
                        <p className="review-original-claim"><strong>Original claim:</strong> {fact.originalClaim}</p>
                        {fact.revisions.length > 0 && <p className="review-original-claim"><strong>Previous wording:</strong> {fact.revisions[fact.revisions.length - 1]}</p>}
                        <label htmlFor={`claim-${fact.id}`}>Corrected claim</label>
                        <textarea id={`claim-${fact.id}`} value={draft} onChange={(event) => setDraft(event.target.value)} rows={3} aria-invalid={Boolean(error)} aria-describedby={error ? `claim-error-${fact.id}` : undefined} />
                        {error && <p className="review-edit-error" id={`claim-error-${fact.id}`}>{error}</p>}
                        <div className="review-actions"><button className="review-action review-action-primary" type="submit">Save correction</button><button className="review-action" type="button" onClick={cancelEdit}>Cancel</button></div>
                      </form>
                    ) : (
                      <>
                        <h3>{fact.claim}</h3>
                        <p className="review-demo-label">Sample content for layout demonstration</p>
                        {fact.revisions.length > 0 && <details className="review-revision-history"><summary>Previous wording ({fact.revisions.length})</summary><ol>{fact.revisions.map((revision, index) => <li key={`${index}-${revision}`}>{revision}</li>)}</ol></details>}
                      </>
                    )}
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
                    <span className={`review-status-label ${detail.className}`}><span aria-hidden="true">{detail.icon}</span> {fact.status}</span>
                    {!isEditing && <div className="review-actions">
                      {fact.status === "Unreviewed" && <><button className="review-action review-action-primary" type="button" onClick={() => setStatus(fact, "Approved")}>Approve</button><button className="review-action review-action-reject" type="button" onClick={() => setStatus(fact, "Rejected")}>Reject</button></>}
                      <button className="review-action" type="button" onClick={() => beginEdit(fact)}>Correct claim</button>
                    </div>}
                  </div>
                </article>
              </li>
            );
          })}
        </ul>
      </section>

      <p className="review-live-message" role="status" aria-live="polite">{announcement}</p>

      <section className="review-next-step" aria-labelledby="next-step-heading">
        <div><p className="review-kicker">What comes next</p><h2 id="next-step-heading">Reviewed facts can guide creative work.</h2><p>Readiness in this demo: {approvedCount} of {facts.length} illustrative claims marked approved. Rejected claims are never counted as approved.</p><p>These sample decisions cannot authorize real creative. Real extraction, evidence review, and a connected backend are required first.</p></div>
        <div className="review-next-control"><button type="button" disabled aria-describedby="next-step-note">Continue to creative work <span aria-hidden="true">↗</span></button><p id="next-step-note">Unavailable in this frontend-only demo. No creative will be generated.</p><Link className="review-readiness-link" href="/projects/sample-northstar/creative">See the illustrative readiness details <span aria-hidden="true">↗</span></Link></div>
      </section>
    </>
  );
}
