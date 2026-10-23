"use client";

import Link from "next/link";
import { useNorthstarProjectState } from "../demo-project-provider";
import { getApprovedDemoFacts } from "../review/demo-facts";
import type { BriefAspectRatio, BriefDuration, CampaignObjective, CampaignPlatform } from "../creative-brief";

const objectives: { value: CampaignObjective; label: string }[] = [
  { value: "awareness", label: "Awareness" },
  { value: "engagement", label: "Engagement" },
  { value: "traffic", label: "Traffic" },
  { value: "conversions", label: "Conversions" },
];
const platforms: { value: CampaignPlatform; label: string }[] = [
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "youtube", label: "YouTube" },
  { value: "other", label: "Other" },
];
const ratios: BriefAspectRatio[] = ["9:16", "1:1", "16:9"];
const durations: BriefDuration[] = [15, 30, 60];

export default function CreativeBriefWorkspace() {
  const { facts, brief, updateBrief, resetBrief } = useNorthstarProjectState();
  const approvedFacts = getApprovedDemoFacts(facts);
  const reliedUponFacts = facts.filter((fact) => brief.reliedUponFactIds.includes(fact.id));
  const unapprovedRelyOns = reliedUponFacts.filter((fact) => fact.status !== "approved");
  const objectiveLabel = objectives.find(({ value }) => value === brief.objective)?.label ?? "Awareness";
  const platformLabel = platforms.find(({ value }) => value === brief.platform)?.label ?? "Other";

  function toggleFact(factId: string, checked: boolean) {
    const ids = checked
      ? [...brief.reliedUponFactIds, factId]
      : brief.reliedUponFactIds.filter((id) => id !== factId);
    updateBrief({ reliedUponFactIds: ids });
  }

  function confirmReset() {
    if (window.confirm("Reset the creative brief to its illustrative Northstar demo defaults?")) resetBrief();
  }

  return (
    <main className="creative-brief-page">
      <nav className="brief-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li><Link href="/#overview">Overview</Link></li>
          <li><Link href="/projects/sample-northstar">Northstar Coffee sample</Link></li>
          <li aria-current="page">Creative brief</li>
        </ol>
      </nav>

      <header className="brief-heading">
        <p className="brief-kicker">Northstar Coffee <span aria-hidden="true">/</span> Illustrative sample</p>
        <h1>Shape the<br /><em>brief.</em></h1>
        <p>A planning workspace for a possible campaign. These defaults are illustrative examples, not user-provided requirements.</p>
      </header>

      <aside className="brief-demo-notice" aria-labelledby="brief-demo-title">
        <span aria-hidden="true">i</span>
        <div><h2 id="brief-demo-title">Demo brief · temporary in-memory state</h2><p>Changes are shared across Northstar project pages in this tab. Refreshing resets this brief and the demo review decisions. Approved means approved for this demo only; it is not independent verification.</p></div>
      </aside>

      <section className="brief-fact-context" aria-labelledby="brief-fact-title">
        <div><p className="brief-kicker">Grounding check</p><h2 id="brief-fact-title">{approvedFacts.length} approved demo {approvedFacts.length === 1 ? "fact" : "facts"} available</h2></div>
        <p>Choose which sample claims this brief relies on. Unreviewed and rejected claims are never treated as approved content.</p>
        <fieldset>
          <legend>Illustrative claims referenced by this brief</legend>
          {facts.map((fact) => (
            <label className="brief-fact-choice" key={fact.id}>
              <input
                type="checkbox"
                checked={brief.reliedUponFactIds.includes(fact.id)}
                onChange={(event) => toggleFact(fact.id, event.currentTarget.checked)}
              />
              <span><strong>{fact.category}:</strong> {fact.claim}</span>
              <span className={`brief-status brief-status-${fact.status}`}>{fact.status}</span>
            </label>
          ))}
        </fieldset>
        {unapprovedRelyOns.length > 0 ? (
          <p className="brief-grounding-warning" role="status"><strong>Review needed.</strong> This brief references {unapprovedRelyOns.map((fact) => fact.status === "rejected" ? `a rejected ${fact.category.toLowerCase()} claim` : `an unreviewed ${fact.category.toLowerCase()} claim`).join(" and ")}. It is not approved for demo copy and must not be presented as verified.</p>
        ) : <p className="brief-grounding-clear" role="status">All selected sample claims are approved for demo use only. No claim has been independently verified.</p>}
        <p className="brief-fact-count">{approvedFacts.length} of {facts.length} sample facts are currently marked approved.</p>
      </section>

      <div className="brief-workspace-grid">
        <form className="brief-form" onSubmit={(event) => event.preventDefault()} aria-label="Illustrative creative brief">
          <div className="brief-form-heading"><div><p className="brief-kicker">Campaign plan</p><h2>Brief details</h2></div><span>DEMO DEFAULTS</span></div>
          <p className="brief-form-intro">Every starting value is a sample prompt. Edit freely; nothing is submitted or saved.</p>

          <div className="brief-field-grid">
            <label className="brief-field">Campaign objective
              <select value={brief.objective} onChange={(event) => updateBrief({ objective: event.currentTarget.value as CampaignObjective })}>
                {objectives.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="brief-field">Platform
              <select value={brief.platform} onChange={(event) => updateBrief({ platform: event.currentTarget.value as CampaignPlatform })}>
                {platforms.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="brief-field">Target audience <span>Illustrative default</span>
              <textarea rows={2} value={brief.targetAudience} onChange={(event) => updateBrief({ targetAudience: event.currentTarget.value })} />
            </label>
            <label className="brief-field">Product or offer <span>Illustrative default</span>
              <input value={brief.productOrOffer} onChange={(event) => updateBrief({ productOrOffer: event.currentTarget.value })} />
            </label>
            <label className="brief-field">Key message <span>Illustrative default</span>
              <textarea rows={2} value={brief.keyMessage} onChange={(event) => updateBrief({ keyMessage: event.currentTarget.value })} />
            </label>
            <label className="brief-field">Value proposition <span>Optional · demo prompt</span>
              <textarea rows={2} value={brief.valueProposition} onChange={(event) => updateBrief({ valueProposition: event.currentTarget.value })} placeholder="Add a value proposition for this demo" />
            </label>
            <label className="brief-field">Aspect ratio
              <select value={brief.aspectRatio} onChange={(event) => updateBrief({ aspectRatio: event.currentTarget.value as BriefAspectRatio })}>
                {ratios.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}
              </select>
            </label>
            <label className="brief-field">Duration
              <select value={brief.duration} onChange={(event) => updateBrief({ duration: Number(event.currentTarget.value) as BriefDuration })}>
                {durations.map((duration) => <option key={duration} value={duration}>{duration} seconds</option>)}
              </select>
            </label>
            <label className="brief-field">Tone and creative direction <span>Illustrative default</span>
              <textarea rows={2} value={brief.tone} onChange={(event) => updateBrief({ tone: event.currentTarget.value })} />
            </label>
            <label className="brief-field">Call to action <span>Illustrative default</span>
              <input value={brief.callToAction} onChange={(event) => updateBrief({ callToAction: event.currentTarget.value })} />
            </label>
          </div>
          <button className="brief-reset" type="button" onClick={confirmReset}>Reset to demo defaults</button>
        </form>

        <aside className="brief-preview" aria-labelledby="brief-preview-title">
          <p className="brief-kicker">Live summary <span aria-hidden="true">·</span> Illustrative only</p>
          <h2 id="brief-preview-title">{brief.productOrOffer || "Untitled demo brief"}</h2>
          <dl>
            <div><dt>Objective</dt><dd>{objectiveLabel}</dd></div>
            <div><dt>Audience</dt><dd>{brief.targetAudience || "Not set"}</dd></div>
            <div><dt>Message</dt><dd>{brief.keyMessage || "Not set"}</dd></div>
            <div><dt>Value proposition</dt><dd>{brief.valueProposition || "Not set"}</dd></div>
            <div><dt>Format</dt><dd>{platformLabel} · {brief.aspectRatio} · {brief.duration}s</dd></div>
            <div><dt>Tone</dt><dd>{brief.tone || "Not set"}</dd></div>
            <div><dt>Call to action</dt><dd>{brief.callToAction || "Not set"}</dd></div>
          </dl>
          <p className="brief-preview-source">References {reliedUponFacts.length} illustrative {reliedUponFacts.length === 1 ? "claim" : "claims"}. This preview is a planning summary, not ad copy.</p>
          <button className="brief-generate" type="button" disabled aria-describedby="brief-generate-note">Generate Ad <span aria-hidden="true">↗</span></button>
          <p id="brief-generate-note" className="brief-generate-note">Ad generation is not implemented. This control does not submit or generate anything.</p>
        </aside>
      </div>

      <footer className="brief-footer"><p>Illustrative demo only · No website scanned · No independent verification · No data saved</p><div><Link href="/projects/sample-northstar/storyboard">Plan storyboard scenes</Link><Link href="/projects/sample-northstar/review">Fact review</Link><Link href="/projects/sample-northstar/creative">Creative readiness</Link><Link href="/projects/sample-northstar">Sample project</Link></div></footer>
    </main>
  );
}
