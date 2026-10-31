"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";

import { login, register, type FormState } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";
import type { ActionError } from "@/lib/action-result";
import { routeActionError } from "@/lib/notify";

export function AuthForm({ mode, next }: { mode: "login" | "register"; next: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(mode === "login" ? login : register, undefined);
  const isLogin = mode === "login";
  const nextQuery = next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
  const otherHref = `${isLogin ? "/register" : "/login"}${nextQuery}`;
  const fieldErrors = state?.fieldErrors ?? {};
  const [inlineError, setInlineError] = useState<ActionError | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setInlineError(state?.error ? routeActionError(state.error) : null);
  }, [state]);

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{isLogin ? "Sign in" : "Create an account"}</h1>
      <p className="mt-2 text-muted">{isLogin ? "Sign in to hold and buy tickets." : "You need an account to hold tickets."}</p>

      <form action={action} className="mt-8 space-y-4">
        <input type="hidden" name="next" value={next} />
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Username</span>
          <input
            name="username"
            defaultValue={state?.values?.username}
            required
            autoComplete="username"
            maxLength={150}
            className="field"
            aria-invalid={fieldErrors.username ? true : undefined}
            aria-describedby={fieldErrors.username ? "username-error" : undefined}
          />
          <FieldError id="username-error" message={fieldErrors.username} />
        </label>
        {!isLogin && (
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Email</span>
            <input
              name="email"
              type="email"
              defaultValue={state?.values?.email}
              required
              autoComplete="email"
              className="field"
              aria-invalid={fieldErrors.email ? true : undefined}
              aria-describedby={fieldErrors.email ? "email-error" : undefined}
            />
            {fieldErrors.email ? (
              <FieldError id="email-error" message={fieldErrors.email}>
                {state?.emailTaken && (
                  <>
                    {" "}
                    <Link href={`/login${nextQuery}`} className="font-medium text-accent underline underline-offset-4">
                      Sign in instead
                    </Link>
                  </>
                )}
              </FieldError>
            ) : (
              <span className="mt-1 block text-xs text-muted">Your QR tickets are sent here.</span>
            )}
          </label>
        )}
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Password</span>
          <input
            name="password"
            type="password"
            required
            minLength={isLogin ? undefined : 8}
            autoComplete={isLogin ? "current-password" : "new-password"}
            className="field"
            aria-invalid={fieldErrors.password ? true : undefined}
            aria-describedby={fieldErrors.password ? "password-error" : undefined}
          />
          <FieldError id="password-error" message={fieldErrors.password} />
        </label>
        {inlineError && <ErrorNote error={inlineError} />}
        <button className="btn btn-primary w-full" disabled={pending}>
          {pending ? "Please wait..." : isLogin ? "Sign in" : "Create account"}
        </button>
      </form>

      <p className="mt-6 text-sm text-muted">
        {isLogin ? "New here? " : "Already have an account? "}
        <Link href={otherHref} className="font-medium text-accent underline-offset-4 hover:underline">
          {isLogin ? "Create an account" : "Sign in"}
        </Link>
      </p>
    </div>
  );
}

function FieldError({ id, message, children }: { id: string; message?: string; children?: React.ReactNode }) {
  if (!message) return null;
  return (
    <span id={id} className="mt-1 block text-sm text-bad">
      {message}
      {children}
    </span>
  );
}
