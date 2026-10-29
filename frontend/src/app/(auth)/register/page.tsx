import type { Metadata } from "next";

import { AuthForm } from "../auth-form";

export const metadata: Metadata = { title: "Sign up" };

export default async function RegisterPage({ searchParams }: PageProps<"/register">) {
  const next = (await searchParams).next;
  return <AuthForm mode="register" next={typeof next === "string" ? next : "/"} />;
}
