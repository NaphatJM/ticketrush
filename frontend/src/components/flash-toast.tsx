"use client";

import { useEffect } from "react";
import { toast } from "sonner";

import { FLASH_COOKIE, FLASH_MESSAGES, type FlashKind } from "@/lib/flash";

export function FlashToast({ flash }: { flash: string | null }) {
  useEffect(() => {
    if (!flash) return;
    document.cookie = `${FLASH_COOKIE}=; Max-Age=0; path=/`;
    const kind = flash.split(".")[0] as FlashKind;
    // The cookie value is unique per action, so a repeated effect updates the same toast instead of stacking a copy.
    if (Object.hasOwn(FLASH_MESSAGES, kind)) toast.success(FLASH_MESSAGES[kind], { id: flash });
  }, [flash]);

  return null;
}
