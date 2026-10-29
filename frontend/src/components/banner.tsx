export function Banner({ src, title, className = "" }: { src: string; title: string; className?: string }) {
  if (!src) {
    return (
      <div className={`flex items-end bg-ink p-4 text-paper ${className}`} aria-hidden>
        <span className="font-display text-2xl font-extrabold leading-none opacity-90">{title}</span>
      </div>
    );
  }
  // Banners are arbitrary HTTPS URLs set by organizers, so they bypass the next/image allowlist.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" className={`object-cover ${className}`} />;
}
