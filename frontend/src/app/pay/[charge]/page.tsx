import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { formatBaht, formatDateTime } from "@/lib/format";
import type { MockCharge } from "@/lib/types";

import { PayButtons } from "./pay-buttons";

export const metadata: Metadata = { title: "Mock payment" };

export default async function PayPage({ params, searchParams }: PageProps<"/pay/[charge]">) {
  const { charge: chargeId } = await params;
  const order = (await searchParams).order;
  if (!/^[\w-]{1,100}$/.test(chargeId) || typeof order !== "string") notFound();

  let charge: MockCharge;
  try {
    charge = await api<MockCharge>(`/mock-gateway/charges/${chargeId}/`);
  } catch (error) {
    if (error instanceof ApiError && error.httpStatus === 404) notFound();
    throw error;
  }

  return (
    <div className="mx-auto max-w-md">
      <div className="stub overflow-hidden">
        <div className="bg-ink px-6 py-4 text-paper">
          <p className="font-mono text-xs uppercase tracking-widest opacity-70">Mock payment provider</p>
          <p className="mt-1 text-sm opacity-80">This page stands in for a real card gateway. No money moves.</p>
        </div>
        <div className="space-y-5 p-6">
          <div>
            <p className="text-sm text-muted">Amount due</p>
            <p className="font-display text-4xl font-extrabold">{formatBaht(charge.amount_satang)}</p>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted">Charge</dt>
            <dd className="truncate font-mono">{charge.charge_id}</dd>
            <dt className="text-muted">Pay before</dt>
            <dd>{formatDateTime(charge.expires_at)}</dd>
            <dt className="text-muted">Status</dt>
            <dd className="font-medium">{charge.status}</dd>
          </dl>
          <PayButtons chargeId={charge.charge_id} orderUuid={order} payable={charge.status === "pending"} />
        </div>
      </div>
    </div>
  );
}
