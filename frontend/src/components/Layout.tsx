import { NavLink, Outlet, useLocation } from "react-router-dom";
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
              <span className="brand-tag">Outside-in organizational diligence</span>
            </NavLink>
            <SystemsIndicator />
          </div>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              New investigation
            </NavLink>
            <NavLink to="/cases">Cases</NavLink>
            <NavLink to="/compare">Compare</NavLink>
            <NavLink to="/evidence">Evidence</NavLink>
            <NavLink to="/how-it-works">How it works</NavLink>
          </nav>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <p>DealScope produces outside-in signals from public data. It supports, and does not replace, management diligence.</p>
      </footer>
    </>
  );
}
