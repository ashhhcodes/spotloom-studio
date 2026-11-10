"use client";

import { useState, type FormEvent } from "react";
import {
  ProductionPackagePreflightError,
  requestProductionPackagePreflight,
  type ProductionPackagePreflightResult,
} from "./production-package-api";

type SubmissionState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "result"; value: ProductionPackagePreflightResult }
  | { status: "error"; message: string };

export default function ProductionPackagePreflight() {
  const [packageJson, setPackageJson] = useState("");
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmission({ status: "loading" });
    try {
      const value = await requestProductionPackagePreflight(packageJson);
      setSubmission({ status: "result", value });
    } catch (error) {
      const message = error instanceof ProductionPackagePreflightError
        ? error.message
        : "Package validation could not be completed. Try again.";
      setSubmission({ status: "error", message });
    }
  }

  return (
    <section className="package-preflight" aria-labelledby="package-preflight-title">
      <div className="package-section-heading">
        <div>
          <p className="package-kicker">Explicit backend action · local/demo only</p>
          <h2 id="package-preflight-title">Check v2 package structure</h2>
        </div>
      </div>
      <p className="package-preflight-boundary">
        Paste a complete v2 package JSON and submit it when ready. The request is sent only after you activate the button, to the configured backend, and this validator does not persist or render it. Structural validation does not establish project ownership, asset existence, storage integrity, trusted readiness, or renderability. Do not use this local/demo screen for public deployment.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="production-package-json">Versioned production package JSON</label>
        <textarea
          id="production-package-json"
          name="productionPackageJson"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          rows={18}
          value={packageJson}
          disabled={submission.status === "loading"}
          onChange={(event) => {
            setPackageJson(event.currentTarget.value);
            setSubmission({ status: "idle" });
          }}
          aria-describedby="package-json-help"
        />
        <p id="package-json-help" className="package-field-note">
          The package must declare <code>spotloom.production-package.v2</code> and a lowercase UUID <code>correlationId</code>. The backend enforces its request-size limit and reports schema findings.
        </p>
        <button type="submit" disabled={submission.status === "loading"}>
          {submission.status === "loading" ? "Checking structure…" : "Validate v2 package"}
        </button>
      </form>
      <div className="package-preflight-result" aria-live={submission.status === "error" ? "assertive" : "polite"} role={submission.status === "error" ? "alert" : "status"}>
        {submission.status === "idle" && <p>No package has been submitted.</p>}
        {submission.status === "loading" && <p>Submitting the current JSON for structural validation…</p>}
        {submission.status === "error" && <p>{submission.message}</p>}
        {submission.status === "result" && (
          <>
            <p className={submission.value.structurallyValid ? "package-preflight-valid" : "package-preflight-invalid"}>
              {submission.value.outcome === "evaluated"
                ? submission.value.structurallyValid ? "V2 package is structurally valid." : "V2 package is structurally invalid."
                : submission.value.outcome === "unsupported" ? "The backend does not support this package contract or profile."
                  : "The backend rejected this package request."}
            </p>
            {submission.value.rendererProfileId && <p>Declared renderer profile: <code>{submission.value.rendererProfileId}</code></p>}
            {submission.value.issues.length > 0 && (
              <ul aria-label="Package validation findings">
                {submission.value.issues.map((issue, index) => (
                  <li key={`${issue.path}-${issue.code}-${index}`}>
                    <code>{issue.path || "package"}</code> · {issue.message} <small>({issue.code})</small>
                  </li>
                ))}
              </ul>
            )}
            <p className="package-field-note">A structurally valid response is not asset resolution, authorization, trusted readiness, or approval to render.</p>
          </>
        )}
      </div>
    </section>
  );
}
