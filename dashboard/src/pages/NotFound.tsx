import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <section className="card">
        <p className="muted">This page doesn't exist.</p>
        <Link to="/">Go to the dashboard</Link>
      </section>
    </>
  );
}
