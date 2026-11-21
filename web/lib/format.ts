// Time/number formatting in IST.
const TZ = "Asia/Kolkata";

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: TZ });
}

export function fmtDayTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date().toLocaleDateString("en-IN", { timeZone: TZ });
  const yest = new Date(Date.now() - 86400000).toLocaleDateString("en-IN", { timeZone: TZ });
  const day = d.toLocaleDateString("en-IN", { timeZone: TZ });
  const prefix = day === today ? "Today" : day === yest ? "Yesterday" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: TZ });
  return `${prefix} ${fmtTime(iso)}`;
}

export function fmtHour(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", timeZone: TZ }).replace(" ", "").toLowerCase();
}

export function fmtDuration(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

export function fmtInr(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: v < 10 ? digits : 0 });
}

export function secondsBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 1000;
}

export const clsLabel: Record<string, string> = {
  person: "Person", car: "Car", motorcycle: "Motorcycle", bicycle: "Bicycle", bus: "Bus", truck: "Truck",
  backpack: "Bag", handbag: "Bag", suitcase: "Bag", laptop: "Laptop", "cell phone": "Phone", bottle: "Bottle", any_bag: "Bag",
};
