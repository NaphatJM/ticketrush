import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md text-center">
      <p className="font-mono text-sm text-accent">404</p>
      <h1 className="mt-2 font-display text-3xl font-extrabold">Not found</h1>
      <p className="mt-3 text-muted">This page does not exist, or it belongs to another account.</p>
      <Link href="/" className="btn btn-primary mt-6">
        Back to events
      </Link>
    </div>
  );
}
