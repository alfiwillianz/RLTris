import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <section className="panel">
      <h1>Page not found</h1>
      <p className="muted">That route does not exist.</p>
      <p>
        <Link to="/">Back to overview</Link>
      </p>
    </section>
  );
}
