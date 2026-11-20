import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  error?: string | null;
  loading?: boolean;
  children?: ReactNode;
  onRetry?: () => void;
}

export function ErrorPanel({ title, error, onRetry }: PanelProps) {
  return (
    <div className="panel error-panel">
      <h3>{title ?? "Request failed"}</h3>
      <p className="mono">{error}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry} type="button">
          Retry
        </button>
      )}
    </div>
  );
}

export function LoadingPanel({ title }: PanelProps) {
  return <div className="panel muted">{title ?? "Loading…"}</div>;
}

export function AsyncState({ error, loading, onRetry }: PanelProps) {
  if (error) return <ErrorPanel error={error} onRetry={onRetry} />;
  if (loading) return <LoadingPanel />;
  return null;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}
