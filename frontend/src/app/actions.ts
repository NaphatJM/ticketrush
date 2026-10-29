"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { ActionResult } from "@/lib/action-result";
import { api, ApiError, clientIp } from "@/lib/api";
import { apiRequest } from "@/lib/api-core";
import { SESSION_COOKIE, sealSession, sessionCookieOptions } from "@/lib/session";
import type { Hold, Order, User } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(error: unknown): { ok: false; error: { code: string; message: string; cid: string | null } } {
  if (error instanceof ApiError) {
    return { ok: false, error: { code: error.code, message: error.message, cid: error.cid } };
  }
  throw error;
}

// Only same-site paths, so a crafted ?next= cannot send the user to another origin.
function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

async function startSession(access: string, refresh: string, user: User) {
  (await cookies()).set(SESSION_COOKIE, sealSession({ access, refresh, user }), sessionCookieOptions);
}

export type FormState = { error?: { code: string; message: string; cid: string | null } } | undefined;

export async function login(_state: FormState, form: FormData): Promise<FormState> {
  const ip = await clientIp();
  try {
    const { body: tokens } = await apiRequest<{ access: string; refresh: string }>("/api/auth/login/", {
      method: "POST",
      body: { username: form.get("username"), password: form.get("password") },
      clientIp: ip,
    });
    const { body: user } = await apiRequest<User>("/api/auth/me/", { token: tokens.access, clientIp: ip });
    await startSession(tokens.access, tokens.refresh, user);
  } catch (error) {
    return failure(error);
  }
  redirect(safeNext(form.get("next")));
}

export async function register(_state: FormState, form: FormData): Promise<FormState> {
  try {
    const { body } = await apiRequest<{ user: User; access: string; refresh: string }>("/api/auth/register/", {
      method: "POST",
      body: { username: form.get("username"), email: form.get("email"), password: form.get("password") },
      clientIp: await clientIp(),
    });
    await startSession(body.access, body.refresh, body.user);
  } catch (error) {
    return failure(error);
  }
  redirect(safeNext(form.get("next")));
}

export async function logout() {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/");
}

export async function holdTickets(eventUuid: string, quantity: number, idempotencyKey: string): Promise<ActionResult<Hold>> {
  if (!UUID.test(eventUuid)) return { ok: false, error: { code: "NOT_FOUND", message: "Event not found.", cid: null } };
  try {
    const hold = await api<Hold>(`/api/events/${eventUuid}/holds/`, { method: "POST", body: { quantity }, idempotencyKey, auth: true });
    return { ok: true, data: hold };
  } catch (error) {
    return failure(error);
  }
}

export async function releaseHold(holdUuid: string): Promise<ActionResult> {
  if (!UUID.test(holdUuid)) return { ok: false, error: { code: "NOT_FOUND", message: "Hold not found.", cid: null } };
  try {
    await api<Hold>(`/api/holds/${holdUuid}/`, { method: "DELETE", auth: true });
    return { ok: true, data: undefined };
  } catch (error) {
    return failure(error);
  }
}

export async function checkout(holdUuid: string, idempotencyKey: string): Promise<ActionResult<{ order: string; charge: string | null }>> {
  if (!UUID.test(holdUuid)) return { ok: false, error: { code: "NOT_FOUND", message: "Hold not found.", cid: null } };
  try {
    const order = await api<Order>(`/api/holds/${holdUuid}/checkout/`, { method: "POST", idempotencyKey, auth: true });
    const pending = order.payment && order.payment.status !== "succeeded" && order.status === "pending_payment";
    const charge = pending ? new URL(order.payment!.payment_url).pathname.split("/").filter(Boolean).pop() ?? null : null;
    return { ok: true, data: { order: order.uuid, charge } };
  } catch (error) {
    return failure(error);
  }
}

export async function payCharge(chargeId: string, orderUuid: string, outcome: "succeeded" | "failed"): Promise<ActionResult> {
  if (!/^[\w-]{1,100}$/.test(chargeId) || !UUID.test(orderUuid)) {
    return { ok: false, error: { code: "NOT_FOUND", message: "Payment not found.", cid: null } };
  }
  try {
    await api(`/mock-gateway/charges/${chargeId}/pay/`, { method: "POST", body: { outcome } });
  } catch (error) {
    return failure(error);
  }
  redirect(`/orders/${orderUuid}`);
}
