import "server-only";

import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

import type { User } from "./types";

export const SESSION_COOKIE = "tr_session";
export const SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export type Session = {
  access: string;
  refresh: string;
  user: User;
};

function key(): Buffer {
  const secret = process.env.SESSION_COOKIE_SECRET ?? "";
  if (Buffer.byteLength(secret) < 32) {
    throw new Error("SESSION_COOKIE_SECRET must be at least 32 bytes");
  }
  return createHash("sha256").update(secret).digest();
}

export function sealSession(session: Session): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(session), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

export function unsealSession(value: string | undefined): Session | null {
  if (!value) return null;
  try {
    const raw = Buffer.from(value, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key(), raw.subarray(0, 12));
    decipher.setAuthTag(raw.subarray(12, 28));
    const body = Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]);
    return JSON.parse(body.toString("utf8")) as Session;
  } catch {
    // A tampered cookie or one sealed with a rotated secret is treated as signed out.
    return null;
  }
}

export const sessionCookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge: SESSION_MAX_AGE_SECONDS,
};

export function tokenExpiresAt(jwt: string): number {
  try {
    const payload = JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf8")) as { exp?: number };
    return (payload.exp ?? 0) * 1000;
  } catch {
    return 0;
  }
}
