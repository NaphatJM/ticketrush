import { NextResponse, type NextRequest } from "next/server";

import { ApiError, apiRequest } from "@/lib/api-core";
import { SESSION_COOKIE, sealSession, sessionCookieOptions, tokenExpiresAt, unsealSession, type Session } from "@/lib/session";

const REFRESH_BEFORE_MS = 60_000;

// Refresh tokens rotate and the old one is blacklisted, so parallel requests in one process share a single refresh call.
const inflight = new Map<string, Promise<Session>>();

function refreshOnce(session: Session): Promise<Session> {
  let pending = inflight.get(session.refresh);
  if (!pending) {
    pending = apiRequest<{ access: string; refresh: string }>("/api/auth/refresh/", {
      method: "POST",
      body: { refresh: session.refresh },
    }).then(({ body }) => ({ ...session, access: body.access, refresh: body.refresh }));
    inflight.set(session.refresh, pending);
    const key = session.refresh;
    setTimeout(() => inflight.delete(key), 30_000);
  }
  return pending;
}

export async function proxy(request: NextRequest) {
  const session = unsealSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session || tokenExpiresAt(session.access) - Date.now() > REFRESH_BEFORE_MS) {
    return NextResponse.next();
  }

  try {
    const sealed = sealSession(await refreshOnce(session));
    request.cookies.set(SESSION_COOKIE, sealed);
    const response = NextResponse.next({ request: { headers: request.headers } });
    response.cookies.set(SESSION_COOKIE, sealed, sessionCookieOptions);
    return response;
  } catch (error) {
    if (error instanceof ApiError && (error.httpStatus === 400 || error.httpStatus === 401)) {
      request.cookies.delete(SESSION_COOKIE);
      const response = NextResponse.next({ request: { headers: request.headers } });
      response.cookies.delete(SESSION_COOKIE);
      return response;
    }
    // The API is down: keep the session so the user is not signed out by an outage.
    return NextResponse.next();
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
