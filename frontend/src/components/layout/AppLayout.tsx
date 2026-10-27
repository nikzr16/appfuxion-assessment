import { BarChart3, FileStack, Upload } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { ChatLauncher } from "../../features/chat/ChatLauncher.tsx";
import { cx } from "../../lib/cx.ts";
import HealthBadge from "../HealthBadge.tsx";
import { LiveRegion } from "../ui/LiveRegion.tsx";
import { ThemeToggle } from "./ThemeToggle.tsx";

const NAV = [
  { to: "/", label: "Upload", Icon: Upload, end: true },
  { to: "/documents", label: "Documents", Icon: FileStack, end: false },
  { to: "/metrics", label: "Metrics", Icon: BarChart3, end: false },
];

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-lg" aria-label="Document Intelligence, home">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-accent" />
        <path d="M10 7h8.5L23 11.5V24a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z" fill="#fff" />
        <path d="M12.5 16.5h7M12.5 19.5h7M12.5 22.5h4" className="stroke-accent" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="leading-tight">
        <span className="block text-sm font-semibold text-fg">Document Intelligence</span>
        <span className="hidden text-xs text-fg-subtle sm:block">Invoices &amp; receipts, checked by AI</span>
      </span>
    </Link>
  );
}

/** Moves focus to the page heading after client-side navigation (PRD D15). */
function useFocusHeadingOnNavigate(): void {
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    document.querySelector<HTMLElement>("main h1")?.focus();
  }, [pathname]);
}

export function AppLayout() {
  useFocusHeadingOnNavigate();

  return (
    <LiveRegion>
      <div className="flex min-h-dvh flex-col">
        <a
          href="#main"
          className="sr-only z-50 rounded-lg bg-accent px-3 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-30 border-b border-border bg-surface/85 backdrop-blur-md">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
            <Logo />
            <nav aria-label="Main" className="order-3 flex w-full gap-1 sm:order-none sm:w-auto">
              {NAV.map(({ to, label, Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cx(
                      "inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors sm:flex-none",
                      isActive ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                    )
                  }
                >
                  <Icon className="size-4" aria-hidden />
                  {label}
                </NavLink>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-2">
              <HealthBadge />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
          <Outlet />
        </main>

        <footer className="border-t border-border">
          <p className="mx-auto max-w-6xl px-4 pt-5 pb-24 text-xs text-fg-subtle sm:px-6 sm:pr-40 sm:pb-5">
            Data is extracted by AI and checked by code. Verify important values against the original document.
          </p>
        </footer>
        <ChatLauncher />
      </div>
    </LiveRegion>
  );
}
