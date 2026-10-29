import "server-only";

import { cookies, headers } from "next/headers";

import { ApiError, apiRequest, type RawOptions } from "./api-core";
import { SESSION_COOKIE, unsealSession } from "./session";

export { ApiError };

export async function clientIp(): Promise<string | null> {
  const incoming = await headers();
  // Vercel sets x-real-ip and overwrites x-forwarded-for, so neither carries a client-chosen value there.
  return incoming.get("x-real-ip") ?? incoming.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null;
}

export async function currentSession() {
  return unsealSession((await cookies()).get(SESSION_COOKIE)?.value);
}

export async function api<T>(path: string, options: Omit<RawOptions, "token" | "clientIp"> & { auth?: boolean } = {}): Promise<T> {
  const session = options.auth ? await currentSession() : null;
  if (options.auth && !session) throw new ApiError(401, "NOT_AUTHENTICATED", "Please sign in.", null);
  const { body } = await apiRequest<T>(path, { ...options, token: session?.access, clientIp: await clientIp() });
  return body;
}

export async function apiPage<T>(path: string): Promise<{ data: T[]; count: number }> {
  const { body, envelope } = await apiRequest<T[]>(path, { clientIp: await clientIp() });
  return { data: body, count: envelope.count ?? body.length };
}
