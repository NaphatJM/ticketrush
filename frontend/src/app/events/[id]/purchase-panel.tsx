"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { toast } from "sonner";

import { checkout, holdTickets, releaseHold } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";
import type { ActionError } from "@/lib/action-result";
import { formatBaht } from "@/lib/format";
import { routeActionError } from "@/lib/notify";
import type { Hold, SaleStatus } from "@/lib/types";

const CHECKOUT_MIN_LEFT_MS = 60_000;

type Props = {
  eventUuid: string;
  saleStatus: SaleStatus;
  saleOpensAt: string;
  maxQuantity: number;
  priceSatang: number;
  signedIn: boolean;
};

function storageKey(eventUuid: string) {
  return `tr:hold:${eventUuid}`;
}

function readStoredHold(eventUuid: string): Hold | null {
  try {
    const raw = sessionStorage.getItem(storageKey(eventUuid));
    const hold = raw ? (JSON.parse(raw) as Hold) : null;
    return hold && new Date(hold.expires_at).getTime() > Date.now() ? hold : null;
  } catch {
    return null;
  }
}

function holdEndingToastId(holdUuid: string) {
  return `hold-ending:${holdUuid}`;
}

function heldMessage(hold: Hold): string {
  const tickets = `${hold.quantity} ${hold.quantity === 1 ? "ticket" : "tickets"} held.`;
  const minutes = Math.floor((new Date(hold.expires_at).getTime() - Date.now()) / 60_000);
  if (minutes < 1) return `${tickets} Less than a minute is left to pay.`;
  return `${tickets} You have ${minutes} ${minutes === 1 ? "minute" : "minutes"} to pay.`;
}

function storeHold(eventUuid: string, hold: Hold | null) {
  try {
    if (hold) sessionStorage.setItem(storageKey(eventUuid), JSON.stringify(hold));
    else sessionStorage.removeItem(storageKey(eventUuid));
  } catch {}
}

export function PurchasePanel({ eventUuid, saleStatus, saleOpensAt, maxQuantity, priceSatang, signedIn }: Props) {
  const router = useRouter();
  const [quantity, setQuantity] = useState(1);
  const [hold, setHold] = useState<Hold | null>(null);
  const [error, setError] = useState<ActionError | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [pending, startTransition] = useTransition();
  // One key per attempt: a resend after a lost response replays the first result instead of holding twice.
  const holdKey = useRef<string | null>(null);
  const checkoutKey = useRef<string | null>(null);

  useEffect(() => {
    // sessionStorage exists only in the browser, so the stored hold is restored after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHold(readStoredHold(eventUuid));
  }, [eventUuid]);

  useEffect(() => {
    if (!hold) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [hold]);

  const remaining = hold ? new Date(hold.expires_at).getTime() - now : 0;
  const expired = hold !== null && remaining <= 0;
  const tooLate = hold !== null && !expired && remaining < CHECKOUT_MIN_LEFT_MS;
  const warnedHold = useRef<string | null>(null);

  useEffect(() => {
    if (!tooLate || !hold || warnedHold.current === hold.uuid) return;
    warnedHold.current = hold.uuid;
    toast.warning("Less than a minute left on your hold. That is too little to pay, so release it and hold again.", { id: holdEndingToastId(hold.uuid) });
  }, [tooLate, hold]);

  useEffect(() => {
    if (expired && hold) toast.dismiss(holdEndingToastId(hold.uuid));
  }, [expired, hold]);

  function onHold() {
    holdKey.current ??= crypto.randomUUID();
    const key = holdKey.current;
    setError(null);
    startTransition(async () => {
      const result = await holdTickets(eventUuid, quantity, key);
      holdKey.current = null;
      if (!result.ok) {
        setError(routeActionError(result.error));
        return;
      }
      toast.success(heldMessage(result.data));
      setHold(result.data);
      setNow(Date.now());
      storeHold(eventUuid, result.data);
      router.refresh();
    });
  }

  function onCheckout() {
    if (!hold) return;
    checkoutKey.current ??= crypto.randomUUID();
    const key = checkoutKey.current;
    setError(null);
    startTransition(async () => {
      const result = await checkout(hold.uuid, key);
      checkoutKey.current = null;
      if (!result.ok) {
        setError(routeActionError(result.error));
        return;
      }
      storeHold(eventUuid, null);
      router.push(result.data.charge ? `/pay/${result.data.charge}?order=${result.data.order}` : `/orders/${result.data.order}`);
    });
  }

  function onRelease() {
    if (!hold) return;
    setError(null);
    startTransition(async () => {
      const result = await releaseHold(hold.uuid);
      if (!result.ok && result.error.code !== "HOLD_NOT_ACTIVE") {
        setError(routeActionError(result.error));
        return;
      }
      toast.dismiss(holdEndingToastId(hold.uuid));
      setHold(null);
      storeHold(eventUuid, null);
      router.refresh();
    });
  }

  function onStartOver() {
    setHold(null);
    storeHold(eventUuid, null);
    router.refresh();
  }

  if (hold && !expired) {
    const minutes = Math.floor(remaining / 60_000);
    const seconds = Math.floor((remaining % 60_000) / 1000);
    return (
      <div className="space-y-4">
        <div className="rounded-xl bg-ink p-4 text-paper">
          <p className="text-sm opacity-80">
            {hold.quantity} {hold.quantity === 1 ? "ticket" : "tickets"} held for you
          </p>
          <p className="font-mono text-4xl font-bold tabular-nums" aria-live="polite">
            {minutes}:{seconds.toString().padStart(2, "0")}
          </p>
          <p className="text-sm opacity-80">Total {formatBaht(priceSatang * hold.quantity)}</p>
        </div>
        <button type="button" className="btn btn-primary w-full" onClick={onCheckout} disabled={pending || tooLate}>
          {pending ? "Working..." : tooLate ? "Too little time left to pay" : "Continue to payment"}
        </button>
        <button type="button" className="btn btn-ghost w-full" onClick={onRelease} disabled={pending}>
          Release tickets
        </button>
        {error && <ErrorNote error={error} />}
      </div>
    );
  }

  if (expired) {
    return (
      <div className="space-y-4">
        <p className="text-sm">Your hold expired and the tickets went back on sale.</p>
        <button type="button" className="btn btn-primary w-full" onClick={onStartOver}>
          Start over
        </button>
      </div>
    );
  }

  if (saleStatus !== "on_sale") {
    const message: Record<Exclude<SaleStatus, "on_sale">, string> = {
      upcoming: `Sale opens ${saleOpensAt}.`,
      sold_out: "Sold out. Held tickets return to sale if their holders do not pay in time.",
      closed: "The sale for this event has closed.",
    };
    return <p className="text-sm text-muted">{message[saleStatus]}</p>;
  }

  if (!signedIn) {
    return (
      <Link href={`/login?next=/events/${eventUuid}`} className="btn btn-primary w-full">
        Sign in to buy
      </Link>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Quantity</span>
        <div className="flex items-center gap-2">
          <button type="button" className="btn btn-ghost size-10 !p-0" onClick={() => setQuantity((q) => Math.max(1, q - 1))} disabled={quantity <= 1} aria-label="Fewer tickets">
            -
          </button>
          <span className="w-8 text-center font-mono text-lg font-bold tabular-nums">{quantity}</span>
          <button type="button" className="btn btn-ghost size-10 !p-0" onClick={() => setQuantity((q) => Math.min(maxQuantity, q + 1))} disabled={quantity >= maxQuantity} aria-label="More tickets">
            +
          </button>
        </div>
      </div>
      <button type="button" className="btn btn-primary w-full text-lg" onClick={onHold} disabled={pending}>
        {pending ? "Holding..." : `Hold ${quantity} for ${formatBaht(priceSatang * quantity)}`}
      </button>
      <p className="text-xs text-muted">Held tickets are yours for 5 minutes while you pay.</p>
      {error && <ErrorNote error={error} />}
    </div>
  );
}
