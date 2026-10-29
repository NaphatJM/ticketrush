import type { ActionError } from "@/lib/action-result";

export function ErrorNote({ error }: { error: ActionError }) {
  return (
    <div role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm">
      <p className="font-medium text-bad">{error.message}</p>
      {error.cid && <p className="mt-1 font-mono text-xs text-muted">Reference: {error.cid}</p>}
    </div>
  );
}
