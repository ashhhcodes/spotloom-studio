"use client";

import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from "react";

type Feedback = { kind: "success" | "error"; message: string };

export function WorkspaceStart() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const manualNameRef = useRef<HTMLInputElement>(null);
  const manualTriggerRef = useRef<HTMLButtonElement>(null);
  const [url, setUrl] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [service, setService] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [manualOpen, setManualOpen] = useState(false);

  useEffect(() => {
    if (!manualOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    manualNameRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [manualOpen]);

  function startFromWebsite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
        setFeedback({ kind: "error", message: "Enter a website address beginning with http:// or https://." });
        return;
      }
      setFeedback({ kind: "success", message: `Prototype ready to review for ${parsed.hostname}. No website was scanned and no project was saved.` });
    } catch {
      setFeedback({ kind: "error", message: "Enter a valid website address, including https://." });
    }
  }

  function startManual(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback({ kind: "success", message: `Manual draft started for ${businessName.trim()} (${service.trim()}). This stays in this page and was not saved.` });
    dialogRef.current?.close();
  }

  function openManual(event: MouseEvent<HTMLButtonElement>) {
    manualTriggerRef.current = event.currentTarget;
    dialogRef.current?.showModal();
    setManualOpen(true);
  }

  function closeManual() {
    setManualOpen(false);
    manualTriggerRef.current?.focus();
  }

  return (
    <>
      <section className="start-panel" aria-labelledby="start-title">
        <div className="start-main">
          <p className="workspace-label">Start a project</p>
          <h2 id="start-title">Bring the business into focus.</h2>
          <p className="start-intro">Add a website to begin with its public story, or enter the essentials yourself. You’ll review extracted claims before they shape any creative work.</p>
          <form className="project-form" onSubmit={startFromWebsite}>
            <label htmlFor="website-url">Business website</label>
            <div className="url-row">
              <input id="website-url" type="url" inputMode="url" autoComplete="url" placeholder="https://yourbusiness.com" value={url} onChange={(event) => { setUrl(event.target.value); setFeedback(null); }} required aria-describedby="url-help" />
              <button className="primary-action" type="submit">Start with website <span aria-hidden="true">↗</span></button>
            </div>
            <p className="form-help" id="url-help">Use a full http:// or https:// address. Prototype only; this page does not fetch or scan the website.</p>
          </form>
          <div className="review-note"><span className="review-icon" aria-hidden="true">i</span><span><strong>Review comes first.</strong> Any future extracted facts will be shown for your approval before they are used.</span></div>
          {feedback && <p className="inline-status" data-kind={feedback.kind} role={feedback.kind === "error" ? "alert" : "status"}>{feedback.message}</p>}
        </div>
        <aside className="start-aside" aria-label="Manual business entry">
          <div><span className="aside-step">Another way to begin</span><h3>Start with what you know.</h3><p>Enter a business name and product or service for a local draft preview.</p></div>
          <button className="secondary-action" ref={manualTriggerRef} type="button" onClick={openManual}>Enter business manually <span aria-hidden="true">＋</span></button>
        </aside>
      </section>

      <section className="projects-section" id="projects" aria-labelledby="projects-title">
        <div className="projects-heading"><div><p className="workspace-label">A starting point</p><h2 id="projects-title">Your workspace</h2></div><p>Sample only · no saved projects yet</p></div>
        <article className="sample-project">
          <div className="sample-art" aria-hidden="true">N<span>.</span></div>
          <div><small>Sample project · Coffee</small><h3>Northstar Coffee</h3><p>A layout example for a small-batch coffee brand. This is illustrative content.</p></div>
          <span className="sample-badge">Sample</span>
        </article>
      </section>

      <dialog className="manual-dialog" ref={dialogRef} aria-labelledby="manual-title" onClose={closeManual} onClick={(event) => { if (event.target === event.currentTarget) dialogRef.current?.close(); }}>
        <div className="dialog-content">
          <div className="dialog-head"><div><h2 id="manual-title">Enter business details</h2><p>These details create a local draft preview only.</p></div><button className="dialog-close" type="button" aria-label="Close manual entry" onClick={() => dialogRef.current?.close()}>×</button></div>
          <form className="manual-form" onSubmit={startManual}>
            <label htmlFor="manual-business">Business name</label>
            <input id="manual-business" ref={manualNameRef} value={businessName} onChange={(event) => setBusinessName(event.target.value)} required pattern=".*\S.*" title="Enter at least one non-space character." maxLength={80} autoComplete="organization" />
            <label htmlFor="manual-service">Product or service</label>
            <input id="manual-service" value={service} onChange={(event) => setService(event.target.value)} required pattern=".*\S.*" title="Enter at least one non-space character." maxLength={120} />
            <button className="primary-action" type="submit">Start local draft <span aria-hidden="true">↗</span></button>
          </form>
        </div>
      </dialog>
    </>
  );
}
