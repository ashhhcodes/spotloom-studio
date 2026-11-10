"use client";

import { SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { IdentityCheckError, verifyBackendIdentity } from "@/app/auth/identity-api";
import "./auth-controls.css";

type CheckState = { kind: "idle" | "checking" | "verified" | "error"; message: string };

export function AuthControlsSlot({ enabled }: { enabled: boolean }) {
  if (!enabled) {
    return <span className="auth-setup-note" role="status">Sign-in setup needed</span>;
  }
  return <ClerkAuthControls />;
}

function ClerkAuthControls() {
  const { isLoaded, isSignedIn, getToken } = useAuth();

  if (!isLoaded) {
    return <span className="auth-status" role="status" aria-live="polite">Loading account…</span>;
  }

  if (!isSignedIn) {
    return (
      <div className="auth-controls" aria-label="Account">
        <SignInButton mode="modal">
          <button className="auth-action" type="button">Sign in</button>
        </SignInButton>
        <SignUpButton mode="modal">
          <button className="auth-action auth-action-secondary" type="button">Create account</button>
        </SignUpButton>
      </div>
    );
  }

  return <SignedInControls getToken={getToken} />;
}

function SignedInControls({ getToken }: { getToken: () => Promise<string | null> }) {
  const [check, setCheck] = useState<CheckState>({ kind: "idle", message: "" });

  async function verifySession() {
    setCheck({ kind: "checking", message: "Checking backend…" });
    try {
      await verifyBackendIdentity(getToken);
      setCheck({ kind: "verified", message: "Backend verified this Clerk session." });
    } catch (error) {
      setCheck({
        kind: "error",
        message: error instanceof IdentityCheckError
          ? error.message
          : "The backend could not verify this session. Try again later.",
      });
    }
  }

  return (
    <div className="auth-controls" aria-label="Account">
      <UserButton />
      <button
        className="auth-action"
        type="button"
        onClick={verifySession}
        disabled={check.kind === "checking"}
      >
        {check.kind === "checking" ? "Checking…" : "Verify backend session"}
      </button>
      {check.message && (
        <span className={`auth-status auth-status-${check.kind}`} role="status" aria-live="polite">
          {check.message}
        </span>
      )}
    </div>
  );
}
