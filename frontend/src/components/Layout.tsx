import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { SystemsIndicator } from "./SystemsIndicator";

function BrandMark() {
  return (
    <svg className="brand-mark" width="32" height="32" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="7" fill="#223a66" />
      <circle cx="15" cy="15" r="6" fill="none" stroke="#4fd1c5" strokeWidth="3" />
      <path d="M20 20l6 6" stroke="#4fd1c5" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

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
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand" aria-label="DealScope home">
            <BrandMark />
            <span>
              <span className="brand-name">DealScope</span>
              <span className="brand-tag">Outside-in organizational diligence</span>
            </span>
          </NavLink>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              New investigation
            </NavLink>
            <NavLink to="/cases">Cases</NavLink>
            <NavLink to="/evidence">Evidence</NavLink>
            <NavLink to="/how-it-works">How it works</NavLink>
          </nav>
          <SystemsIndicator />
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        DealScope produces outside-in signals from public data. It supports, and does not replace, management diligence.
      </footer>
    </>
  );
}
