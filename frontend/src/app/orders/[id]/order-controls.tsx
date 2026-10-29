"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { checkout } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";
import type { ActionError } from "@/lib/action-result";

const POLL_MS = 1500;
const POLL_LIMIT = 80;

export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  const polls = useRef(0);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      polls.current += 1;
      if (polls.current > POLL_LIMIT) {
        clearInterval(timer);
        return;
      }
      router.refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active, router]);

  return null;
}

export function RetryPayment({ holdUuid, label, note }: { holdUuid: string; label: string; note: string }) {
  const router = useRouter();
  const [error, setError] = useState<ActionError | null>(null);
  const [pending, startTransition] = useTransition();
  const key = useRef<string | null>(null);

  function onRetry() {
    key.current ??= crypto.randomUUID();
    const attempt = key.current;
    setError(null);
    startTransition(async () => {
      const result = await checkout(holdUuid, attempt);
      key.current = null;
      if (!result.ok) {
        setError(result.error);
        return;
      }
      router.push(result.data.charge ? `/pay/${result.data.charge}?order=${result.data.order}` : `/orders/${result.data.order}`);
    });
  }

  return (
    <div className="space-y-3">
      <p>{note}</p>
      <button type="button" className="btn btn-primary" onClick={onRetry} disabled={pending}>
        {pending ? "Working..." : label}
      </button>
      {error && <ErrorNote error={error} />}
    </div>
  );
}
