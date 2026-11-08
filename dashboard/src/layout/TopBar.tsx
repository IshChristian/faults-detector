import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { roleLabel } from "../auth/types";

const dateFormat = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

export function TopBar() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (!user) return null;
  const initials = user.full_name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <header className="topbar">
      <div className="site-name">My site</div>
      <div className="topbar-right">
        <span className="date-badge num">{dateFormat.format(new Date())}</span>
        <div className="user-menu" ref={menuRef}>
          <button
            type="button"
            className="user-button"
            aria-label={`Account menu: ${user.full_name}, ${roleLabel(user)}`}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <span className="avatar" aria-hidden="true">{initials}</span>
            <span className="user-text">
              <span className="user-name">{user.full_name}</span>
              <span className="user-role">{roleLabel(user)}</span>
            </span>
          </button>
          {open && (
            <div className="menu" role="menu">
              <button type="button" role="menuitem" className="menu-item" onClick={() => logout()}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
