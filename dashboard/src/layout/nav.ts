export type NavItem = { path: string; label: string; icon: IconName };
export type IconName = "live" | "faults" | "sessions" | "cameras" | "settings";

export const NAV_ITEMS: NavItem[] = [
  { path: "/live", label: "Live Operations", icon: "live" },
  { path: "/faults", label: "Fault Center", icon: "faults" },
  { path: "/sessions", label: "Sessions", icon: "sessions" },
  { path: "/cameras", label: "Cameras & Screens", icon: "cameras" },
  { path: "/settings", label: "Settings", icon: "settings" },
];
