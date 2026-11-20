import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

function BrandMark() {
  return (
    <svg className="brand-mark-svg" viewBox="0 0 28 28" width="28" height="28" aria-hidden="true">
      <rect x="0.5" y="0.5" width="27" height="27" rx="4" fill="#111318" stroke="#2c3240" />
      <rect x="5" y="13" width="5" height="5" rx="0.75" fill="#22d3ee" />
      <rect x="11.5" y="13" width="5" height="5" rx="0.75" fill="#22d3ee" />
      <rect x="18" y="13" width="5" height="5" rx="0.75" fill="#22d3ee" />
      <rect x="11.5" y="6.5" width="5" height="5" rx="0.75" fill="#f59e0b" />
    </svg>
  );
}

function NavIcon({ name }: { name: string }) {
  const props = {
    width: 15,
    height: 15,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "overview":
      return (
        <svg {...props}>
          <rect x="2" y="2" width="5" height="5" rx="1" />
          <rect x="9" y="2" width="5" height="3.5" rx="1" />
          <rect x="9" y="7.5" width="5" height="6.5" rx="1" />
          <rect x="2" y="9" width="5" height="5" rx="1" />
        </svg>
      );
    case "runs":
      return (
        <svg {...props}>
          <path d="M2 12.5h12" />
          <path d="M3.5 9.5l3-3.5 2.5 2 3.5-4.5" />
        </svg>
      );
    case "compare":
      return (
        <svg {...props}>
          <path d="M3 13V7" />
          <path d="M8 13V3" />
          <path d="M13 13V5.5" />
        </svg>
      );
    case "tournaments":
      return (
        <svg {...props}>
          <path d="M4.5 3h7v3.5a3.5 3.5 0 0 1-7 0V3z" />
          <path d="M4.5 4.5H2.5v1.5a2 2 0 0 0 2 2" />
          <path d="M11.5 4.5h2v1.5a2 2 0 0 1-2 2" />
          <path d="M8 10v3" />
          <path d="M5.5 13h5" />
        </svg>
      );
    case "replays":
      return (
        <svg {...props}>
          <rect x="2" y="3" width="12" height="10" rx="1.5" />
          <path d="M6.5 6v4l3.5-2-3.5-2z" fill="currentColor" stroke="none" />
        </svg>
      );
    default:
      return (
        <svg {...props}>
          <path d="M3 4.5h10v8H3z" />
          <path d="M5.5 4.5V2.5h5v2" />
          <path d="M6 8.5h4" />
        </svg>
      );
  }
}

const NAV = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/runs", label: "Runs", icon: "runs" },
  { to: "/compare", label: "Compare", icon: "compare" },
  { to: "/tournaments", label: "Tournaments", icon: "tournaments" },
  { to: "/replays", label: "Replays", icon: "replays" },
  { to: "/checkpoints", label: "Checkpoints", icon: "checkpoints" },
];

export default function Layout() {
  const { data: health } = useAsync(() => api.health(), [], 15000);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <BrandMark />
          <div>
            <div className="brand-title">TetrisRL</div>
            <div className="brand-subtitle">S2 · SRS+ Arena</div>
          </div>
        </div>

        <div className="nav-label">Workspace</div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
            >
              <NavIcon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="health-row">
            <span className={health?.status === "ok" ? "dot dot-ok" : "dot dot-off"} aria-hidden />
            <span className="mono tiny">
              {health?.status === "ok" ? "API ONLINE" : health ? "API DEGRADED" : "API OFFLINE"}
            </span>
          </div>
          {health && (
            <div className="health-meta mono tiny muted">
              <span>v{health.version}</span>
              <span>·</span>
              <span>{health.trainer_available ? "trainer ready" : "no trainer"}</span>
            </div>
          )}
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
