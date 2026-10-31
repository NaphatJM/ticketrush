import { toast } from "sonner";

import type { ActionError } from "./action-result";
import { describeError, isToastError } from "./messages";

export function logActionError(error: ActionError) {
  console.error(`TicketRush API error ${error.code}`, { cid: error.cid, message: error.message });
}

// Returns the error when it belongs inline, so a caller never shows the same failure twice.
export function routeActionError(error: ActionError): ActionError | null {
  if (!isToastError(error.code)) return error;
  logActionError(error);
  const { message, tone } = describeError(error.code);
  if (tone === "warning") toast.warning(message);
  else toast.error(message);
  return null;
}
