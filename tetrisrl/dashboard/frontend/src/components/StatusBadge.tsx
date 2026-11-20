import { statusClass } from "../lib/format";

export default function StatusBadge({ status }: { status: string | null | undefined }) {
  return <span className={statusClass(status)}>{status ?? "unknown"}</span>;
}
