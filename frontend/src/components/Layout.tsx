import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { SystemsIndicator } from "./SystemsIndicator";

/** Editorial masthead (serif wordmark, tagline, text nav, heavy ink rule), page outlet and hairline footer. */
export function Layout() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="masthead">
        <div className="masthead-inner">
          <div className="masthead-top">
            <NavLink to="/" className="brand" aria-label="DealScope home">
              <span className="brand-name">
                Deal<i>Scope</i>
              </span>
              <span className="brand-tag">Team check for investors</span>
            </NavLink>
            <SystemsIndicator />
          </div>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Search
            </NavLink>
            <NavLink to="/cases">History</NavLink>
            <NavLink to="/how-it-works" className="nav-quiet">
              How it works
            </NavLink>
          </nav>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <p>DealScope reads public data to flag team risks. It supports, and does not replace, your own diligence.</p>
        <nav className="footer-links" aria-label="More">
          <Link to="/compare">Compare</Link>
          <Link to="/evidence">Evidence</Link>
        </nav>
      </footer>
    </>
  );
}
