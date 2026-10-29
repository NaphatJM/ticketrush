import "server-only";

const TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    readonly httpStatus: number,
    readonly code: string,
    message: string,
    readonly cid: string | null,
  ) {
    super(message);
  }
}

export type RawOptions = {
  method?: string;
  body?: unknown;
  token?: string;
  clientIp?: string | null;
  idempotencyKey?: string;
};

type Envelope = {
  status?: { code?: string; message?: string };
  data?: unknown;
  count?: number;
  links?: unknown;
};

export async function apiRequest<T>(path: string, options: RawOptions = {}): Promise<{ body: T; envelope: Envelope }> {
  const base = process.env.API_BASE_URL;
  if (!base) throw new Error("API_BASE_URL is not set");

  const requestHeaders: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) requestHeaders["Content-Type"] = "application/json";
  if (options.token) requestHeaders.Authorization = `Bearer ${options.token}`;
  if (options.idempotencyKey) requestHeaders["Idempotency-Key"] = options.idempotencyKey;
  // The API trusts BFF-Client-IP only next to the shared secret, so both are always built here, never copied from the browser.
  const secret = process.env.BFF_SHARED_SECRET;
  if (secret && options.clientIp) {
    requestHeaders["BFF-Secret"] = secret;
    requestHeaders["BFF-Client-IP"] = options.clientIp;
  }

  let response: Response;
  try {
    response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
      method: options.method ?? "GET",
      headers: requestHeaders,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    throw new ApiError(503, timedOut ? "API_TIMEOUT" : "API_UNREACHABLE", "The ticketing service is not responding. Please try again.", null);
  }

  const cid = response.headers.get("Correlation-ID");
  let envelope: Envelope = {};
  try {
    envelope = (await response.json()) as Envelope;
  } catch {
    if (response.ok) throw new ApiError(502, "BAD_RESPONSE", "The ticketing service sent an unreadable response.", cid);
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      envelope.status?.code ?? `HTTP_${response.status}`,
      envelope.status?.message ?? "The request failed.",
      cid,
    );
  }
  return { body: envelope.data as T, envelope };
}
