import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/runs", label: "Runs" },
  { to: "/compare", label: "Compare" },
  { to: "/tournaments", label: "Tournaments" },
  { to: "/replays", label: "Replays" },
  { to: "/checkpoints", label: "Checkpoints" },
];

export default function Layout() {
  const { data: health } = useAsync(() => api.health(), [], 15000);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ▦
          </span>
          <div>
            <div className="brand-title">TetrisRL</div>
            <div className="brand-subtitle">experiment arena</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="health-row">
            <span className={health?.status === "ok" ? "dot dot-ok" : "dot dot-off"} aria-hidden />
            <span>{health?.status === "ok" ? "API connected" : health ? "API degraded" : "API offline"}</span>
          </div>
          {health && (
            <>
              <div className="tiny muted">v{health.version}</div>
              <div className="tiny muted">
                trainer: {health.trainer_available ? "available" : "missing"}
              </div>
            </>
          )}
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
