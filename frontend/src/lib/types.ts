export type SaleStatus = "upcoming" | "on_sale" | "sold_out" | "closed";

export type User = {
  uuid: string;
  username: string;
  email: string;
  role: string;
};

export type Event = {
  uuid: string;
  title: string;
  summary: string;
  category: string;
  banner_url: string;
  venue_name: string;
  starts_at: string;
  ends_at: string | null;
  sale_opens_at: string;
  sale_closes_at: string;
  sale_status: SaleStatus;
  capacity: number;
  available: number;
  price_satang: number;
  max_per_user: number;
};

export type EventDetail = Event & {
  description: string;
  important_info: string;
  presented_by: string;
  venue_address: string;
  venue_map_url: string;
};

export type EventSummary = Pick<Event, "uuid" | "title" | "banner_url" | "venue_name" | "starts_at" | "ends_at">;

export type Hold = {
  uuid: string;
  event: string;
  quantity: number;
  status: "active" | "converted" | "expired" | "released";
  expires_at: string;
  created_on: string;
};

export type Payment = {
  uuid: string;
  status: "created" | "pending" | "succeeded" | "failed";
  amount_satang: number;
  payment_url: string;
  expires_at: string;
};

export type Ticket = {
  uuid: string;
  seq: number;
  code: string;
  issued_at: string;
};

export type OrderStatus = "pending_payment" | "paid" | "failed" | "expired" | "paid_unfulfilled";

export type Order = {
  uuid: string;
  hold: string;
  event: EventSummary;
  quantity: number;
  amount_satang: number;
  status: OrderStatus;
  paid_at: string | null;
  created_on: string;
  payment: Payment | null;
  tickets: Ticket[];
};

export type MockCharge = {
  charge_id: string;
  amount_satang: number;
  status: string;
  expires_at: string;
};

export type Page<T> = {
  count: number;
  links: { next: string | null; previous: string | null };
  data: T[];
};
