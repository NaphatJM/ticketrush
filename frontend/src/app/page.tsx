import Link from "next/link";

import { Banner } from "@/components/banner";
import { StatusPill } from "@/components/status-pill";
import { apiPage } from "@/lib/api";
import { categoryLabel, formatBaht, formatDayMonth } from "@/lib/format";
import type { Event } from "@/lib/types";

export default async function EventsPage() {
  const { data: events } = await apiPage<Event>("/api/events/?page_size=60");

  return (
    <div>
      <section className="mb-10 max-w-2xl">
        <h1 className="font-display text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
          Hold your seat
          <br />
          <span className="text-accent">before it&apos;s gone.</span>
        </h1>
        <p className="mt-4 text-lg text-muted">
          Tickets are reserved the moment you hold them and kept for five minutes while you pay. No overselling, no double charges.
        </p>
      </section>

      {events.length === 0 ? (
        <p className="stub p-8 text-muted">No events are on the calendar yet.</p>
      ) : (
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {events.map((event) => (
            <li key={event.uuid}>
              <EventCard event={event} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EventCard({ event }: { event: Event }) {
  const date = formatDayMonth(event.starts_at);
  const soldPercent = event.capacity ? Math.round(((event.capacity - event.available) / event.capacity) * 100) : 0;

  return (
    <Link href={`/events/${event.uuid}`} className="stub group flex h-full flex-col overflow-hidden transition-colors hover:border-ink/40">
      <div className="relative">
        <Banner src={event.banner_url} title={event.title} className="aspect-[16/9] w-full" />
        <div className="absolute left-3 top-3">
          <StatusPill status={event.sale_status} />
        </div>
      </div>
      <div className="flex flex-1 gap-4 p-4">
        <div className="w-14 shrink-0 text-center">
          <div className="text-xs font-semibold uppercase text-accent">{date.weekday}</div>
          <div className="font-display text-lg font-extrabold leading-tight">{date.day}</div>
          <div className="font-mono text-xs text-muted">{date.time}</div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted">{categoryLabel(event.category)}</p>
          <h2 className="font-display text-lg font-semibold leading-snug group-hover:underline">{event.title}</h2>
          <p className="truncate text-sm text-muted">{event.venue_name}</p>
        </div>
      </div>
      <div className="perforation mx-4 flex items-center justify-between gap-3 py-3 text-sm">
        <span className="font-semibold">{formatBaht(event.price_satang)}</span>
        <span className="flex items-center gap-2 text-muted">
          <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line" aria-hidden>
            <span className="block h-full bg-accent" style={{ width: `${soldPercent}%` }} />
          </span>
          {event.available.toLocaleString("en-US")} left
        </span>
      </div>
    </Link>
  );
}
