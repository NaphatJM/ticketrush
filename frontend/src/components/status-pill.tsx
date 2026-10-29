import { SALE_STATUS_LABEL } from "@/lib/format";
import type { SaleStatus } from "@/lib/types";

const TONE: Record<SaleStatus, string> = {
  on_sale: "bg-accent text-accent-ink",
  upcoming: "border border-line bg-card text-ink",
  sold_out: "bg-ink text-paper",
  closed: "border border-line bg-card text-muted",
};

export function StatusPill({ status }: { status: SaleStatus }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${TONE[status]}`}>
      {status === "on_sale" && <span className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none" />}
      {SALE_STATUS_LABEL[status]}
    </span>
  );
}
