import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell() {
  return (
    <div className="app">
      <Sidebar />
      <div className="panel">
        <TopBar />
        <main className="workspace" id="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
