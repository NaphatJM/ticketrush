import type { Metadata } from "next";
import { Bricolage_Grotesque, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import Link from "next/link";

import { logout } from "./actions";
import "./globals.css";
import { currentSession } from "@/lib/api";

const display = Bricolage_Grotesque({ variable: "--font-display", subsets: ["latin"], weight: ["600", "800"] });
const body = Instrument_Sans({ variable: "--font-body", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"], weight: ["500", "700"] });

export const metadata: Metadata = {
  title: { default: "TicketRush", template: "%s · TicketRush" },
  description: "Flash-sale tickets that are never oversold.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const session = await currentSession();

  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <header className="border-b border-line">
          <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
            <Link href="/" className="font-display text-xl font-extrabold tracking-tight">
              Ticket<span className="text-accent">Rush</span>
            </Link>
            <div className="flex items-center gap-1 text-sm sm:gap-3">
              {session ? (
                <>
                  <Link href="/me/tickets" className="rounded-full px-3 py-2 font-medium hover:bg-card">
                    My tickets
                  </Link>
                  <span className="hidden text-muted sm:inline">{session.user.username}</span>
                  <form action={logout}>
                    <button className="rounded-full px-3 py-2 text-muted hover:bg-card hover:text-ink">Sign out</button>
                  </form>
                </>
              ) : (
                <>
                  <Link href="/login" className="rounded-full px-3 py-2 font-medium hover:bg-card">
                    Sign in
                  </Link>
                  <Link href="/register" className="btn btn-primary !px-4 !py-2 text-sm">
                    Sign up
                  </Link>
                </>
              )}
            </div>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-4 py-6 text-sm text-muted sm:px-6">
            <span>TicketRush: a flash-sale ticketing demo. Payments use a mock gateway; no real money moves.</span>
            <a href="https://github.com/NaphatJM/ticketrush" className="underline-offset-4 hover:underline">
              Source on GitHub
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
