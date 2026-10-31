"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { toast } from "sonner";

import { checkout } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";
import type { ActionError } from "@/lib/action-result";
import { routeActionError } from "@/lib/notify";

const POLL_BUDGET_MS = 120_000;

function pollDelayMs(attempt: number): number {
  if (attempt < 4) return 1500;
  if (attempt < 8) return 3000;
  return 5000;
}

export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();

  useEffect(() => {
    if (!active) return;
    let polls = 0;
    let waitedMs = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (waitedMs >= POLL_BUDGET_MS) return;
      const delay = pollDelayMs(polls);
      timer = setTimeout(() => {
        polls += 1;
        waitedMs += delay;
        router.refresh();
        schedule();
      }, delay);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [active, router]);

  return null;
}

export type PaymentState = "waiting" | "issuing" | "paid" | "failed" | "other";

// Announces a payment outcome once: on arrival from the payment page, or when polling sees the order change.
export function PaymentToasts({ orderUuid, state, fromPay }: { orderUuid: string; state: PaymentState; fromPay: boolean }) {
  const previous = useRef<PaymentState | null>(null);

  useEffect(() => {
    const before = previous.current;
    previous.current = state;
    if (before === state) return;
    const announce = before === null ? fromPay : before === "waiting" || before === "issuing";
    if (fromPay && before === null) window.history.replaceState(null, "", window.location.pathname);
    if (!announce) return;

    const id = `payment:${orderUuid}`;
    if (state === "waiting" || state === "issuing") {
      toast.info("Waiting for the payment provider to confirm your payment.", { id, duration: POLL_BUDGET_MS });
    } else if (state === "paid") {
      toast.success("Payment received. Your tickets are ready.", { id, duration: 6000 });
    } else if (state === "failed") {
      toast.error("Your payment was declined. Your tickets stay held until the hold expires.", { id, duration: 8000 });
    } else {
      toast.dismiss(id);
    }
  }, [orderUuid, state, fromPay]);

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
        setError(routeActionError(result.error));
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
