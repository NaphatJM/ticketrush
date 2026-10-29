export type ActionError = { code: string; message: string; cid: string | null };

export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: ActionError };
