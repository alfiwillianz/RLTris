import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import Board, { MiniPiece } from "../components/Board";
import { AsyncState } from "../components/Panels";
import { formatNumber, winnerLabel } from "../lib/format";
import type { Replay, ReplayPlayerStats, ReplaySnapshot, ReplayTickSide } from "../types";

const SPEEDS = [0.5, 1, 2, 4];

const STAT_LABELS: [keyof ReplayPlayerStats, string][] = [
  ["pieces", "Pieces"],
  ["lines", "Lines"],
  ["attack", "Attack generated"],
  ["attack_sent", "Attack sent"],
  ["cancelled", "Garbage cancelled"],
  ["garbage_received", "Garbage received"],
  ["garbage_inserted", "Garbage inserted"],
  ["four_lines", "Tetrises"],
  ["tspins", "T-spins"],
  ["mini_tspins", "Mini T-spins"],
  ["perfect_clears", "Perfect clears"],
  ["max_combo", "Max combo"],
  ["max_b2b", "Max B2B"],
  ["surges", "Surges"],
  ["holds", "Holds"],
  ["final_height", "Final height"],
  ["final_holes", "Final holes"],
];

function PlayerStatsChips({ snapshot }: { snapshot: ReplaySnapshot | null }) {
  if (!snapshot) return null;
  return (
    <div className="player-stats">
      <span className="chip">
        combo <b>{snapshot.combo}</b>
      </span>
      <span className={snapshot.b2b ? "chip chip-active" : "chip"}>
        b2b <b>{snapshot.b2b ? "on" : "off"}</b>
      </span>
      <span className="chip">
        charge <b>{(snapshot.b2b_charge ?? 0).toFixed(2)}</b>
      </span>
      <span className={snapshot.surge ? "chip chip-active" : "chip"}>
        surge <b>{snapshot.surge}</b>
      </span>
      <span className={snapshot.pending_garbage > 0 ? "chip chip-warn" : "chip"}>
        garbage <b>{snapshot.pending_garbage}</b>
      </span>
      <span className="chip">
        lines <b>{snapshot.lines}</b>
      </span>
      <span className="chip">
        attack <b>{snapshot.attack}</b>
      </span>
      <span className="chip">
        pieces <b>{snapshot.pieces}</b>
      </span>
    </div>
  );
}

function QueuePanel({ snapshot }: { snapshot: ReplaySnapshot | null }) {
  if (!snapshot) return null;
  return (
    <div className="queue-row">
      <div className="queue-block">
        <span className="muted tiny mono">HOLD</span>
        <MiniPiece name={snapshot.hold} size={6} />
      </div>
      <div className="queue-block">
        <span className="muted tiny mono">NEXT</span>
        <div className="queue-next-list">
          {snapshot.next.length ? (
            snapshot.next.slice(0, 5).map((name, idx) => <MiniPiece key={`${idx}-${name}`} name={name} size={5} />)
          ) : (
            <span className="mini-piece-empty">—</span>
          )}
        </div>
      </div>
    </div>
  );
}

function EventDetails({ side, label }: { side: ReplayTickSide | undefined; label: string }) {
  if (!side) return null;
  const fields: [string, string][] = [
    ["action", String(side.action ?? "—")],
    ["piece", `${side.piece ?? "?"} @ ${side.column ?? "?"} (r${side.rotation ?? "?"})`],
    ["lines", String(side.lines ?? 0)],
    ["attack", String(side.attack ?? 0)],
    ["sent", String(side.sent ?? 0)],
    ["cancelled", String(side.cancelled ?? 0)],
    ["garbage", String(side.garbage_inserted ?? 0)],
  ];
  return (
    <div className="event-card">
      <div className="event-title">{label}</div>
      <div className="event-grid">
        {fields.map(([key, value]) => (
          <div key={key} className="tiny">
            <span className="muted">{key}</span> <b>{value}</b>
          </div>
        ))}
      </div>
      <div className="event-tags">
        {side.spin && <span className="chip chip-active">{side.mini ? "mini T-spin" : "T-spin"}</span>}
        {side.perfect_clear && <span className="chip chip-active">perfect clear</span>}
        {side.hold && <span className="chip">hold used</span>}
        {side.top_out && <span className="chip chip-warn">top out</span>}
        {Boolean(side.clear) && <span className="chip">{JSON.stringify(side.clear)}</span>}
      </div>
      {side.garbage_events && side.garbage_events.length > 0 && (
        <div className="tiny muted mono">garbage: {JSON.stringify(side.garbage_events)}</div>
      )}
    </div>
  );
}

export default function ReplayViewer() {
  const { matchId = "" } = useParams();
  const { data: replay, error, loading, refresh } = useAsync(() => api.replay(matchId), [matchId]);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);

  const frameCount = replay?.frames.length ?? 0;
  const lastFrame = Math.max(0, frameCount - 1);

  useEffect(() => {
    setFrame(0);
    setPlaying(false);
  }, [matchId]);

  useEffect(() => {
    if (!playing || frameCount <= 1) return;
    if (frame >= lastFrame) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setFrame((current) => Math.min(current + 1, lastFrame)), 500 / speed);
    return () => window.clearTimeout(timer);
  }, [playing, frame, speed, frameCount, lastFrame]);

  const snapshots = replay?.frames[frame];
  const tick = replay?.ticks[frame];
  const result = replay?.result;

  const stats = useMemo(() => result?.stats ?? [], [result]);
  const winnerText = result ? winnerLabel(result.winner) : "—";

  const attackLog = useMemo(() => {
    if (!replay) return [] as { tick: number; side: "a" | "b"; label: string; event: ReplayTickSide }[];
    const entries: { tick: number; side: "a" | "b"; label: string; event: ReplayTickSide }[] = [];
    const start = Math.max(0, frame - 19);
    for (let index = start; index <= frame; index += 1) {
      const tickEntry = replay.ticks[index];
      if (!tickEntry) continue;
      (["a", "b"] as const).forEach((side) => {
        const event = tickEntry[side];
        if (
          event &&
          (event.lines ||
            event.attack ||
            event.sent ||
            event.cancelled ||
            event.garbage_inserted ||
            event.spin ||
            event.top_out)
        ) {
          entries.push({ tick: tickEntry.t, side, label: replay.agents[side], event });
        }
      });
    }
    return entries.reverse().slice(0, 20);
  }, [replay, frame]);

  const step = (delta: number) => {
    setPlaying(false);
    setFrame((current) => Math.max(0, Math.min(lastFrame, current + delta)));
  };

  return (
    <section>
      <div className="breadcrumb">
        <Link to="/replays">Replays</Link> / <span className="mono">{matchId}</span>
      </div>
      <header className="page-header">
        <div>
          <h1>Replay</h1>
          <p className="muted mono">{matchId}</p>
        </div>
        <button className="btn" type="button" onClick={refresh}>
          Reload
        </button>
      </header>

      <AsyncState error={error} loading={loading && !replay} onRetry={refresh} />

      {replay && (
        <>
          <div className="panel">
            <div className="replay-meta">
              <div>
                <span className="muted">Agents</span>
                <div className="mono">
                  {replay.agents.a} vs {replay.agents.b}
                </div>
              </div>
              <div>
                <span className="muted">Seed</span>
                <div className="mono">{replay.seed}</div>
              </div>
              <div>
                <span className="muted">Result</span>
                <div>
                  <b>{winnerText}</b> <span className="muted tiny">({replay.result.reason})</span>
                </div>
              </div>
              <div>
                <span className="muted">Ticks</span>
                <div className="mono">{replay.result.ticks}</div>
              </div>
              <div>
                <span className="muted">Frames</span>
                <div className="mono">{frameCount}</div>
              </div>
              <div>
                <span className="muted">Version</span>
                <div className="mono">{replay.version}</div>
              </div>
            </div>
          </div>

          <div className="panel replay-panel">
            <div className="replay-controls">
              <button className="btn btn-small" type="button" onClick={() => step(-1)} disabled={frame === 0}>
                ◀ step
              </button>
              <button
                className="btn btn-primary btn-small"
                type="button"
                onClick={() => setPlaying((value) => !value)}
                disabled={frameCount <= 1}
              >
                {playing ? "❚❚ pause" : "▶ play"}
              </button>
              <button
                className="btn btn-small"
                type="button"
                onClick={() => step(1)}
                disabled={frame >= lastFrame}
              >
                step ▶
              </button>
              <button className="btn btn-small" type="button" onClick={() => setFrame(0)}>
                ⏮ first
              </button>
              <button className="btn btn-small" type="button" onClick={() => setFrame(lastFrame)}>
                last ⏭
              </button>
              <label className="speed-control">
                speed
                <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
                  {SPEEDS.map((value) => (
                    <option key={value} value={value}>
                      {value}x
                    </option>
                  ))}
                </select>
              </label>
              <span className="tiny muted">
                frame {formatNumber(frame)} / {formatNumber(lastFrame)} · tick{" "}
                {tick?.t !== undefined ? tick.t : frame}
              </span>
            </div>
            <input
              className="scrubber"
              type="range"
              min={0}
              max={lastFrame}
              value={frame}
              onChange={(event) => {
                setPlaying(false);
                setFrame(Number(event.target.value));
              }}
            />

            <div className="boards-row">
              <div className="player-column">
                <Board snapshot={snapshots?.a ?? null} label={replay.agents.a} subtitle="player A" />
                <QueuePanel snapshot={snapshots?.a ?? null} />
                <PlayerStatsChips snapshot={snapshots?.a ?? null} />
              </div>
              <div className="player-column">
                <Board snapshot={snapshots?.b ?? null} label={replay.agents.b} subtitle="player B" />
                <QueuePanel snapshot={snapshots?.b ?? null} />
                <PlayerStatsChips snapshot={snapshots?.b ?? null} />
              </div>
            </div>

            <div className="events-row">
              <EventDetails side={tick?.a} label={`A · ${replay.agents.a}`} />
              <EventDetails side={tick?.b} label={`B · ${replay.agents.b}`} />
            </div>

            <div className="event-log">
              <h3>Recent clears &amp; attacks</h3>
              {attackLog.length === 0 ? (
                <p className="muted tiny">No attack or clear events in the last 20 ticks.</p>
              ) : (
                <ul className="plain-list">
                  {attackLog.map((entry) => (
                    <li key={`${entry.tick}-${entry.side}`} className="tiny event-log-row">
                      <span className="muted mono">t{entry.tick}</span>
                      <span className="mono">{entry.label}</span>
                      <span>
                        {entry.event.piece ?? "?"}{" "}
                        {entry.event.lines ? `${entry.event.lines} lines` : "no clear"}
                        {entry.event.spin ? (entry.event.mini ? " · mini spin" : " · spin") : ""}
                      </span>
                      <span className="muted">
                        atk {entry.event.attack ?? 0} · sent {entry.event.sent ?? 0} · cancel{" "}
                        {entry.event.cancelled ?? 0} · garbage {entry.event.garbage_inserted ?? 0}
                      </span>
                      {entry.event.top_out && <span className="status status-failed">top out</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="panel">
            <h2>Final match statistics</h2>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th className="num">{replay.agents.a}</th>
                    <th className="num">{replay.agents.b}</th>
                  </tr>
                </thead>
                <tbody>
                  {STAT_LABELS.map(([key, label]) => (
                    <tr key={key}>
                      <td>{label}</td>
                      <td className="num">{stats[0] ? formatNumber(Number(stats[0][key])) : "—"}</td>
                      <td className="num">{stats[1] ? formatNumber(Number(stats[1][key])) : "—"}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>Top-out reason</td>
                    <td className="num tiny">{stats[0]?.top_out_reason || "—"}</td>
                    <td className="num tiny">{stats[1]?.top_out_reason || "—"}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            {replay.result.invalid_actions && (
              <p className="tiny muted">
                Invalid agent actions: A {replay.result.invalid_actions[0] ?? 0}, B{" "}
                {replay.result.invalid_actions[1] ?? 0}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
