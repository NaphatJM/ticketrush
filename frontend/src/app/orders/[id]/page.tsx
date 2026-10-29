import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { TicketCard } from "@/components/ticket-card";
import { api, ApiError } from "@/lib/api";
import { redirectIfSignedOut, requireSession } from "@/lib/auth";
import { formatBaht, formatDateTime, ORDER_STATUS_LABEL } from "@/lib/format";
import type { Order } from "@/lib/types";

import { AutoRefresh, RetryPayment } from "./order-controls";

export const metadata: Metadata = { title: "Your order" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function OrderPage({ params }: PageProps<"/orders/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  await requireSession(`/orders/${id}`);

  let order: Order;
  try {
    order = await api<Order>(`/api/orders/${id}/`, { auth: true });
  } catch (error) {
    if (error instanceof ApiError && error.httpStatus === 404) notFound();
    redirectIfSignedOut(error, `/orders/${id}`);
  }

  const payment = order.payment;
  const waitingForWebhook = order.status === "pending_payment" && payment?.status === "pending";
  const chargeId = payment?.payment_url ? new URL(payment.payment_url).pathname.split("/").filter(Boolean).pop() : null;
  const issuing = order.status === "paid" && order.tickets.length < order.quantity;

  return (
    <div className="mx-auto max-w-3xl">
      <AutoRefresh active={waitingForWebhook || issuing} />
      <p className="text-sm text-muted">Order {order.uuid}</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">{order.event.title}</h1>
      <p className="mt-1 text-muted">
        {formatDateTime(order.event.starts_at)} · {order.event.venue_name}
      </p>

      <div className="stub mt-8 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Status</p>
            <p className={`font-display text-2xl font-extrabold ${order.status === "paid" ? "text-ok" : order.status === "pending_payment" ? "" : "text-bad"}`}>
              {ORDER_STATUS_LABEL[order.status]}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm text-muted">
              {order.quantity} {order.quantity === 1 ? "ticket" : "tickets"}
            </p>
            <p className="font-display text-2xl font-extrabold">{formatBaht(order.amount_satang)}</p>
          </div>
        </div>

        <div className="perforation -mx-5 mt-5 px-5 pt-5 text-sm">
          {order.status === "pending_payment" && payment?.status === "created" && (
            <RetryPayment holdUuid={order.hold} label="Continue to payment" note="Your payment has not reached the gateway yet." />
          )}
          {order.status === "pending_payment" && payment?.status === "pending" && chargeId && (
            <div className="space-y-3">
              <p className="flex items-center gap-2">
                <span className="size-2 animate-pulse rounded-full bg-warn motion-reduce:animate-none" />
                Waiting for the payment provider to confirm. This page updates by itself.
              </p>
              <Link href={`/pay/${chargeId}?order=${order.uuid}`} className="text-accent underline-offset-4 hover:underline">
                Have not paid yet? Open the payment page
              </Link>
            </div>
          )}
          {order.status === "failed" && <RetryPayment holdUuid={order.hold} label="Try another payment" note="The payment was declined. Your tickets are still held until the hold expires." />}
          {order.status === "expired" && (
            <p>
              The hold expired before payment, so the tickets went back on sale.{" "}
              <Link href={`/events/${order.event.uuid}`} className="text-accent underline-offset-4 hover:underline">
                Try again
              </Link>
            </p>
          )}
          {order.status === "paid_unfulfilled" && (
            <p>Your payment arrived after the last tickets were sold. An operator will contact you about a refund. Quote order {order.uuid}.</p>
          )}
          {order.status === "paid" && (
            <p>
              Paid {order.paid_at ? formatDateTime(order.paid_at) : ""}.{" "}
              {issuing ? "Issuing your tickets..." : "Your tickets are below and on their way to your email."}
            </p>
          )}
        </div>
      </div>

      {order.tickets.length > 0 && (
        <section className="mt-10">
          <h2 className="font-display text-xl font-semibold">Your tickets</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {order.tickets.map((ticket) => (
              <TicketCard key={ticket.uuid} ticket={ticket} eventTitle={order.event.title} total={order.quantity} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
