import type { IconName } from "./nav";

const PATHS: Record<IconName, string> = {
  live: "M12 5c-5 0-9 7-9 7s4 7 9 7 9-7 9-7-4-7-9-7Zm0 10a3 3 0 1 1 0-6 3 3 0 0 1 0 6Z",
  faults: "M12 3 2 20h20L12 3Zm0 6v5m0 3h.01",
  sessions: "M4 5h16v14H4zM10 9l5 3-5 3V9Z",
  cameras: "M3 7h12v10H3zM15 10l6-3v10l-6-3",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm8 4-2-.7-.5-1.3 1-1.9-1.6-1.6-1.9 1-1.3-.5L13 4h-2l-.7 2-1.3.5-1.9-1-1.6 1.6 1 1.9-.5 1.3L4 11v2l2 .7.5 1.3-1 1.9 1.6 1.6 1.9-1 1.3.5.7 2h2l.7-2 1.3-.5 1.9 1 1.6-1.6-1-1.9.5-1.3 2-.7v-2Z",
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
