import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Checkpoints from "./pages/Checkpoints";
import Compare from "./pages/Compare";
import NewRun from "./pages/NewRun";
import NotFound from "./pages/NotFound";
import Overview from "./pages/Overview";
import ReplayViewer from "./pages/ReplayViewer";
import Replays from "./pages/Replays";
import RunDetail from "./pages/RunDetail";
import Runs from "./pages/Runs";
import TournamentDetail from "./pages/TournamentDetail";
import Tournaments from "./pages/Tournaments";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Overview />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/new" element={<NewRun />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/tournaments" element={<Tournaments />} />
          <Route path="/tournaments/:tournamentId" element={<TournamentDetail />} />
          <Route path="/replays" element={<Replays />} />
          <Route path="/replays/:matchId" element={<ReplayViewer />} />
          <Route path="/checkpoints" element={<Checkpoints />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
