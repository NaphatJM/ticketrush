import "server-only";

import { redirect } from "next/navigation";

import { ApiError, currentSession } from "./api";

export async function requireSession(next: string) {
  const session = await currentSession();
  if (!session) redirect(`/login?next=${encodeURIComponent(next)}`);
  return session;
}

export function redirectIfSignedOut(error: unknown, next: string): never {
  if (error instanceof ApiError && error.httpStatus === 401) redirect(`/login?next=${encodeURIComponent(next)}`);
  throw error;
}
