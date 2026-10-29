import type { OrderStatus, SaleStatus } from "./types";

const TIME_ZONE = "Asia/Bangkok";

const baht = new Intl.NumberFormat("en-US", { style: "currency", currency: "THB", currencyDisplay: "narrowSymbol", minimumFractionDigits: 0, maximumFractionDigits: 2 });

export function formatBaht(satang: number): string {
  return baht.format(satang / 100);
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const dayMonth = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, day: "numeric", month: "short" });
const weekdayShort = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, weekday: "short" });
const clock = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" });

export function formatDateTime(iso: string): string {
  return `${dateTime.format(new Date(iso))} (GMT+7)`;
}

export function formatDayMonth(iso: string): { day: string; weekday: string; time: string } {
  const date = new Date(iso);
  return { day: dayMonth.format(date), weekday: weekdayShort.format(date), time: clock.format(date) };
}

export const SALE_STATUS_LABEL: Record<SaleStatus, string> = {
  upcoming: "Sale not open",
  on_sale: "On sale",
  sold_out: "Sold out",
  closed: "Sale closed",
};

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  pending_payment: "Awaiting payment",
  paid: "Paid",
  failed: "Payment failed",
  expired: "Expired",
  paid_unfulfilled: "Paid, needs attention",
};

export function categoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}
