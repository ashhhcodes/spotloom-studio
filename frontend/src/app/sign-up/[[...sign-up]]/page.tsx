import { Suspense } from "react";
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Suspense fallback={<AuthPageFallback label="Loading account creation…" />}>
        <SignUp />
      </Suspense>
    </div>
  );
}

function AuthPageFallback({ label }: { label: string }) {
  return <span className="auth-status" role="status" aria-live="polite">{label}</span>;
}
