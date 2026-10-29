import QRCode from "qrcode";

import type { Ticket } from "@/lib/types";

export async function TicketCard({ ticket, eventTitle, total }: { ticket: Ticket; eventTitle: string; total: number }) {
  const svg = await QRCode.toString(ticket.code, { type: "svg", margin: 1, errorCorrectionLevel: "M" });

  return (
    <div className="stub flex flex-col items-center p-4 text-center">
      <div className="w-full max-w-[200px] rounded-lg bg-white p-2 [&>svg]:h-auto [&>svg]:w-full" dangerouslySetInnerHTML={{ __html: svg }} />
      <p className="mt-3 font-display font-semibold">{eventTitle}</p>
      <p className="text-sm text-muted">
        Ticket {ticket.seq} of {total}
      </p>
      <p className="mt-2 w-full break-all font-mono text-[10px] leading-tight text-muted">{ticket.code}</p>
    </div>
  );
}
