"use client";

import { useEffect } from "react";

import type { ActionError } from "@/lib/action-result";
import { describeError } from "@/lib/messages";
import { logActionError } from "@/lib/notify";

export function ErrorNote({ error }: { error: ActionError }) {
  useEffect(() => logActionError(error), [error]);

  return (
    <div role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm">
      <p className="font-medium text-bad">{describeError(error.code).message}</p>
    </div>
  );
}
