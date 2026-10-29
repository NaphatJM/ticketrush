import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Banner } from "@/components/banner";
import { StatusPill } from "@/components/status-pill";
import { api, ApiError, currentSession } from "@/lib/api";
import { categoryLabel, formatBaht, formatDateTime } from "@/lib/format";
import type { EventDetail } from "@/lib/types";

import { PurchasePanel } from "./purchase-panel";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function loadEvent(id: string): Promise<EventDetail> {
  if (!UUID.test(id)) notFound();
  try {
    return await api<EventDetail>(`/api/events/${id}/`);
  } catch (error) {
    if (error instanceof ApiError && error.httpStatus === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({ params }: PageProps<"/events/[id]">): Promise<Metadata> {
  const event = await loadEvent((await params).id);
  return { title: event.title, description: event.summary };
}

export default async function EventPage({ params }: PageProps<"/events/[id]">) {
  const { id } = await params;
  const [event, session] = await Promise.all([loadEvent(id), currentSession()]);

  return (
    <article>
      {event.banner_url && (
        <div className="stub mb-8 overflow-hidden">
          <Banner src={event.banner_url} title={event.title} className="aspect-[21/9] max-h-[420px] w-full" />
        </div>
      )}

      <div className="grid gap-10 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill status={event.sale_status} />
            <span className="text-sm uppercase tracking-wide text-muted">{categoryLabel(event.category)}</span>
          </div>
          <h1 className="mt-3 font-display text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl">{event.title}</h1>
          {event.presented_by && <p className="mt-2 text-muted">Presented by {event.presented_by}</p>}
          {event.summary && <p className="mt-5 text-lg">{event.summary}</p>}

          <dl className="mt-8 grid gap-4 sm:grid-cols-2">
            <Fact label="Starts">{formatDateTime(event.starts_at)}</Fact>
            {event.ends_at && <Fact label="Ends">{formatDateTime(event.ends_at)}</Fact>}
            {event.venue_name && (
              <Fact label="Venue">
                {event.venue_name}
                {event.venue_address && <span className="block text-sm text-muted">{event.venue_address}</span>}
                {event.venue_map_url && (
                  <a href={event.venue_map_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-sm text-accent underline-offset-4 hover:underline">
                    Open map
                  </a>
                )}
              </Fact>
            )}
            <Fact label="Ticket sale">
              {formatDateTime(event.sale_opens_at)}
              <span className="block text-sm text-muted">until {formatDateTime(event.sale_closes_at)}</span>
            </Fact>
          </dl>

          {event.description && (
            <section className="mt-10">
              <h2 className="font-display text-xl font-semibold">About this event</h2>
              <p className="mt-3 whitespace-pre-line leading-relaxed">{event.description}</p>
            </section>
          )}
          {event.important_info && (
            <section className="mt-8 rounded-xl border border-warn/40 bg-warn/10 p-5">
              <h2 className="font-display text-lg font-semibold">Important information</h2>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed">{event.important_info}</p>
            </section>
          )}
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="stub p-5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-display text-3xl font-extrabold">{formatBaht(event.price_satang)}</span>
              <span className="text-sm text-muted">per ticket</span>
            </div>
            <p className="mt-1 text-sm text-muted">
              {event.available.toLocaleString("en-US")} of {event.capacity.toLocaleString("en-US")} left · up to {event.max_per_user} per person
            </p>
            <div className="perforation -mx-5 mt-5 px-5 pt-5">
              <PurchasePanel
                eventUuid={event.uuid}
                saleStatus={event.sale_status}
                saleOpensAt={formatDateTime(event.sale_opens_at)}
                maxQuantity={Math.max(1, Math.min(event.max_per_user, event.available))}
                priceSatang={event.price_satang}
                signedIn={session !== null}
              />
            </div>
          </div>
        </aside>
      </div>
    </article>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-l-2 border-accent pl-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}
