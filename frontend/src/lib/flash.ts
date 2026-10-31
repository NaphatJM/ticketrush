// Carries a one-time success message across a server action redirect; the browser deletes it after showing it.
export const FLASH_COOKIE = "tr_flash";

export const FLASH_MESSAGES = {
  registered: "Welcome to TicketRush. Your account is ready.",
  signed_out: "You have signed out.",
} as const;

export type FlashKind = keyof typeof FLASH_MESSAGES;
