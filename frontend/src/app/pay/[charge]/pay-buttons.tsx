"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { payCharge } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";
import type { ActionError } from "@/lib/action-result";

export function PayButtons({ chargeId, orderUuid, payable }: { chargeId: string; orderUuid: string; payable: boolean }) {
  const [error, setError] = useState<ActionError | null>(null);
  const [pending, startTransition] = useTransition();

  function settle(outcome: "succeeded" | "failed") {
    setError(null);
    startTransition(async () => {
      const result = await payCharge(chargeId, orderUuid, outcome);
      if (result && !result.ok) setError(result.error);
    });
  }

  if (!payable) {
    return (
      <Link href={`/orders/${orderUuid}`} className="btn btn-primary w-full">
        Back to your order
      </Link>
    );
  }

  return (
    <div className="space-y-3">
      <button type="button" className="btn btn-primary w-full text-lg" onClick={() => settle("succeeded")} disabled={pending}>
        {pending ? "Processing..." : "Pay now"}
      </button>
      <button type="button" className="btn btn-ghost w-full" onClick={() => settle("failed")} disabled={pending}>
        Decline the payment
      </button>
      {error && <ErrorNote error={error} />}
    </div>
  );
}
