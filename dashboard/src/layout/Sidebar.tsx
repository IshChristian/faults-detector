import { NavLink } from "react-router-dom";
import { Icon } from "./Icon";
import { NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">V</span>
        <span className="brand-name">VisionGuard</span>
      </div>
      <nav aria-label="Main">
        <ul className="nav-list">
          {NAV_ITEMS.map((item) => (
            <li key={item.path}>
              <NavLink to={item.path} className="nav-link" title={item.label}>
                <Icon name={item.icon} />
                <span className="nav-label">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
