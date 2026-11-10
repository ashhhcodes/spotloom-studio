import { Suspense } from "react";
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Suspense fallback={<AuthPageFallback label="Loading sign-in…" />}>
        <SignIn />
      </Suspense>
    </div>
  );
}

function AuthPageFallback({ label }: { label: string }) {
  return <span className="auth-status" role="status" aria-live="polite">{label}</span>;
}
