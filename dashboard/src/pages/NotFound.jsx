import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <section className="soc-glass mx-auto mt-16 max-w-md p-8 text-center">
      <p className="soc-kicker">404</p>
      <h1 className="mt-1 text-xl font-medium text-soc-text">Page not found</h1>
      <p className="mt-2 text-sm text-soc-muted">The page you requested does not exist.</p>
      <Link to="/" className="soc-btn-primary mt-5">
        Back to overview
      </Link>
    </section>
  );
}
