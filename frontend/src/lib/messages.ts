export type ErrorTone = "error" | "warning";

export const FALLBACK_MESSAGE = "Something went wrong. Please try again.";

const ERROR_MESSAGES: Record<string, { message: string; tone?: ErrorTone }> = {
  SOLD_OUT: { message: "Sold out. Tickets may return if other buyers do not pay in time." },
  PER_USER_LIMIT: { message: "You already hold the most tickets allowed for this event." },
  SALE_NOT_OPEN: { message: "Ticket sales for this event are not open right now." },
  SALES_PAUSED: { message: "Sales are paused for a moment. Please try again shortly.", tone: "warning" },
  SIGN_IN_PAUSED: { message: "Sign-in is paused for a moment. Please try again shortly.", tone: "warning" },
  HOLD_EXPIRING: { message: "Not enough time left on your hold to pay. Release it and hold again.", tone: "warning" },
  PAYMENTS_UNAVAILABLE: { message: "Payments are unavailable right now. Your tickets stay held; please try again shortly." },
  INVALID_CREDENTIALS: { message: "Wrong username or password." },
  NOT_AUTHENTICATED: { message: "Your session has ended. Please sign in again." },
  THROTTLED: { message: "Too many attempts. Please wait a minute and try again." },
  IN_PROGRESS: { message: "Your previous request is still being processed. Please wait a moment." },
  API_TIMEOUT: { message: "The ticketing service is not responding. Please try again." },
  API_UNREACHABLE: { message: "The ticketing service is not responding. Please try again." },
  HOLD_NOT_ACTIVE: { message: "This hold is no longer active." },
  HOLD_HAS_ORDER: { message: "These tickets are already in an order." },
  ORDER_NOT_PAYABLE: { message: "This order can no longer be paid." },
  CHARGE_NOT_PENDING: { message: "This payment has already been settled." },
  CHARGE_EXPIRED: { message: "This payment link has expired." },
  NOT_FOUND: { message: "We could not find that." },
  USERNAME_TAKEN: { message: "This username is already taken." },
  EMAIL_TAKEN: { message: "This email already has an account." },
};

// Shown as a toast; every other code is shown inline next to the control that failed.
const TOAST_CODES = new Set([
  "SOLD_OUT",
  "PER_USER_LIMIT",
  "SALE_NOT_OPEN",
  "SALES_PAUSED",
  "SIGN_IN_PAUSED",
  "HOLD_EXPIRING",
  "PAYMENTS_UNAVAILABLE",
  "INVALID_CREDENTIALS",
  "THROTTLED",
  "IN_PROGRESS",
  "API_TIMEOUT",
  "API_UNREACHABLE",
]);

export function describeError(code: string): { message: string; tone: ErrorTone } {
  const entry = ERROR_MESSAGES[code];
  return { message: entry?.message ?? FALLBACK_MESSAGE, tone: entry?.tone ?? "error" };
}

export function isToastError(code: string): boolean {
  return TOAST_CODES.has(code);
}

export type AuthField = "username" | "email" | "password";

const FIELD_MESSAGES: Record<AuthField, [RegExp, string][]> = {
  username: [
    [/only letters|valid username/i, "Use letters, numbers, and @ . + - _ only."],
    [/at most|no more than/i, "Use at most 150 characters."],
  ],
  email: [
    [/valid email/i, "Enter a valid email address."],
    [/at most|no more than/i, "This email address is too long."],
  ],
  password: [
    [/too short/i, "Use at least 8 characters."],
    [/too common/i, "This password is too common. Pick another."],
    [/entirely numeric/i, "Use letters as well as numbers."],
    [/too similar/i, "Too similar to your username or email."],
  ],
};

const FIELD_FALLBACK: Record<AuthField, string> = {
  username: "Check your username.",
  email: "Check your email address.",
  password: "Pick a different password.",
};

// The API flattens validation errors into "[field] message" lines; map each to our own wording.
export function authFieldErrors(apiMessage: string): Partial<Record<AuthField, string>> {
  const errors: Partial<Record<AuthField, string>> = {};
  for (const line of apiMessage.split("\n")) {
    const match = line.match(/^\[(\w+)\] (.*)$/);
    if (!match || !(match[1] in FIELD_MESSAGES)) continue;
    const field = match[1] as AuthField;
    if (errors[field]) continue;
    errors[field] = FIELD_MESSAGES[field].find(([pattern]) => pattern.test(match[2]))?.[1] ?? FIELD_FALLBACK[field];
  }
  return errors;
}
