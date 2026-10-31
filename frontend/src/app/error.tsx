"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => console.error("TicketRush page error", { digest: error.digest }), [error]);

  return (
    <div className="mx-auto max-w-md text-center">
      <h1 className="font-display text-3xl font-extrabold">Something went wrong</h1>
      <p className="mt-3 text-muted">The page could not load. The ticketing service may be busy; please try again.</p>
      <button type="button" className="btn btn-primary mt-6" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
