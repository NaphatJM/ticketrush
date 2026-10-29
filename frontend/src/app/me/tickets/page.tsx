import type { Metadata } from "next";
import Link from "next/link";

import { Banner } from "@/components/banner";
import { TicketCard } from "@/components/ticket-card";
import { api } from "@/lib/api";
import { redirectIfSignedOut, requireSession } from "@/lib/auth";
import { formatBaht, formatDateTime, ORDER_STATUS_LABEL } from "@/lib/format";
import type { Order } from "@/lib/types";

export const metadata: Metadata = { title: "My tickets" };

export default async function MyTicketsPage() {
  await requireSession("/me/tickets");

  let orders: Order[];
  try {
    orders = await api<Order[]>("/api/me/orders/?page_size=50", { auth: true });
  } catch (error) {
    redirectIfSignedOut(error, "/me/tickets");
  }

  const paid = orders.filter((order) => order.tickets.length > 0);
  const others = orders.filter((order) => order.tickets.length === 0);

  return (
    <div>
      <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">My tickets</h1>

      {orders.length === 0 && (
        <div className="stub mt-8 p-8">
          <p className="text-muted">You have no orders yet.</p>
          <Link href="/" className="btn btn-primary mt-4">
            Browse events
          </Link>
        </div>
      )}

      <div className="mt-8 space-y-10">
        {paid.map((order) => (
          <section key={order.uuid}>
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="font-display text-xl font-semibold">{order.event.title}</h2>
                <p className="text-sm text-muted">
                  {formatDateTime(order.event.starts_at)} · {order.event.venue_name}
                </p>
              </div>
              <Link href={`/orders/${order.uuid}`} className="text-sm text-accent underline-offset-4 hover:underline">
                Order details
              </Link>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {order.tickets.map((ticket) => (
                <TicketCard key={ticket.uuid} ticket={ticket} eventTitle={order.event.title} total={order.quantity} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {others.length > 0 && (
        <section className="mt-12">
          <h2 className="font-display text-xl font-semibold">Other orders</h2>
          <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
            {others.map((order) => (
              <li key={order.uuid}>
                <Link href={`/orders/${order.uuid}`} className="flex items-center gap-4 p-4 hover:bg-card">
                  <Banner src={order.event.banner_url} title="" className="size-12 shrink-0 rounded-lg" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{order.event.title}</p>
                    <p className="text-sm text-muted">
                      {order.quantity} {order.quantity === 1 ? "ticket" : "tickets"} · {formatBaht(order.amount_satang)}
                    </p>
                  </div>
                  <span className="text-sm font-medium">{ORDER_STATUS_LABEL[order.status]}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
