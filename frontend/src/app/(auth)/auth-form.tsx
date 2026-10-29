"use client";

import Link from "next/link";
import { useActionState } from "react";

import { login, register, type FormState } from "@/app/actions";
import { ErrorNote } from "@/components/error-note";

export function AuthForm({ mode, next }: { mode: "login" | "register"; next: string }) {
  const [state, action, pending] = useActionState<FormState, FormData>(mode === "login" ? login : register, undefined);
  const isLogin = mode === "login";
  const otherHref = `${isLogin ? "/register" : "/login"}${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{isLogin ? "Sign in" : "Create an account"}</h1>
      <p className="mt-2 text-muted">{isLogin ? "Sign in to hold and buy tickets." : "You need an account to hold tickets."}</p>

      <form action={action} className="mt-8 space-y-4">
        <input type="hidden" name="next" value={next} />
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Username</span>
          <input name="username" required autoComplete="username" maxLength={150} className="field" />
        </label>
        {!isLogin && (
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Email</span>
            <input name="email" type="email" required autoComplete="email" className="field" />
            <span className="mt-1 block text-xs text-muted">Your QR tickets are sent here.</span>
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
          />
        </label>
        {state?.error && <ErrorNote error={state.error} />}
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
