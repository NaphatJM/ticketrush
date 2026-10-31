import Link from "next/link";

import { Banner } from "@/components/banner";
import { StatusPill } from "@/components/status-pill";
import { apiPage } from "@/lib/api";
import { categoryLabel, formatBaht, formatDayMonth, SALE_STATUS_LABEL } from "@/lib/format";
import { EVENT_CATEGORIES, type Event, type EventCategory, type SaleStatus } from "@/lib/types";

const STATUS_FILTERS = ["on_sale", "upcoming", "sold_out"] as const satisfies readonly SaleStatus[];

type StatusFilter = (typeof STATUS_FILTERS)[number];

type Filters = { status: StatusFilter | null; category: EventCategory | null; q: string };

const Q_MAX_LENGTH = 100;

function pick<T extends string>(value: string | string[] | undefined, allowed: readonly T[]): T | null {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function filterHref(filters: Filters, change: Partial<Filters>): string {
  const next = { ...filters, ...change };
  const params = new URLSearchParams();
  if (next.status) params.set("status", next.status);
  if (next.category) params.set("category", next.category);
  if (next.q) params.set("q", next.q);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export default async function EventsPage({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  const filters: Filters = {
    status: pick(params.status, STATUS_FILTERS),
    category: pick(params.category, EVENT_CATEGORIES),
    q: typeof params.q === "string" ? params.q.replaceAll("\x00", "").trim().slice(0, Q_MAX_LENGTH) : "",
  };
  const query = new URLSearchParams({ page_size: "60" });
  if (filters.status) query.set("status", filters.status);
  if (filters.category) query.set("category", filters.category);
  if (filters.q) query.set("q", filters.q);
  const { data: events } = await apiPage<Event>(`/api/events/?${query}`);
  const filtered = Boolean(filters.status || filters.category || filters.q);

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

      <div className="mb-8 space-y-3">
        <form action="/" role="search" className="flex gap-2">
          {filters.status && <input type="hidden" name="status" value={filters.status} />}
          {filters.category && <input type="hidden" name="category" value={filters.category} />}
          <label className="sr-only" htmlFor="event-search">
            Search events
          </label>
          <input
            id="event-search"
            name="q"
            type="search"
            defaultValue={filters.q}
            maxLength={Q_MAX_LENGTH}
            placeholder="Search by event or venue"
            className="field max-w-md"
          />
          <button className="btn btn-ghost shrink-0">Search</button>
        </form>
        <FilterRow label="Sale status">
          <Chip href={filterHref(filters, { status: null })} active={!filters.status}>
            Any status
          </Chip>
          {STATUS_FILTERS.map((status) => (
            <Chip key={status} href={filterHref(filters, { status })} active={filters.status === status}>
              {SALE_STATUS_LABEL[status]}
            </Chip>
          ))}
        </FilterRow>
        <FilterRow label="Category">
          <Chip href={filterHref(filters, { category: null })} active={!filters.category}>
            All categories
          </Chip>
          {EVENT_CATEGORIES.map((category) => (
            <Chip key={category} href={filterHref(filters, { category })} active={filters.category === category}>
              {categoryLabel(category)}
            </Chip>
          ))}
        </FilterRow>
      </div>

      {events.length === 0 ? (
        <div className="stub p-8 text-center">
          {filtered ? (
            <>
              <p className="font-display text-lg font-semibold">No events match these filters.</p>
              <p className="mt-1 text-muted">
                {filters.q ? "Try different search words, another status or category," : "Try another status or category,"} or clear the filters to see
                everything.
              </p>
              <Link href="/" className="btn btn-ghost mt-5">
                Clear filters
              </Link>
            </>
          ) : (
            <p className="text-muted">No events are on the calendar yet.</p>
          )}
        </div>
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

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <nav aria-label={label} className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">{children}</ul>
    </nav>
  );
}

function Chip({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <li>
      <Link
        href={href}
        scroll={false}
        aria-current={active ? "page" : undefined}
        className={`inline-flex whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
          active ? "border-ink bg-ink text-paper" : "border-line bg-card text-ink hover:border-ink/40"
        }`}
      >
        {children}
      </Link>
    </li>
  );
}

function EventCard({ event }: { event: Event }) {
  const date = formatDayMonth(event.starts_at);
  const leftPercent = event.capacity ? Math.round((event.available / event.capacity) * 100) : 0;
  const left = event.available.toLocaleString("en-US");

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
          <span
            role="meter"
            aria-label="Tickets left"
            aria-valuemin={0}
            aria-valuemax={event.capacity}
            aria-valuenow={event.available}
            aria-valuetext={`${left} of ${event.capacity.toLocaleString("en-US")} tickets left`}
            className="h-1.5 w-16 overflow-hidden rounded-full bg-line"
          >
            <span className="block h-full bg-accent" style={{ width: `${leftPercent}%` }} />
          </span>
          <span aria-hidden>{left} left</span>
        </span>
      </div>
    </Link>
  );
}
