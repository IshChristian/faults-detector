import { EmptyState } from "./EmptyState";

export function Cameras() {
  return (
    <>
      <h1>Cameras &amp; Screens</h1>
      <EmptyState
        title="No cameras connected yet."
        body="Add your first camera to begin monitoring."
        action={
          <button type="button" className="btn btn-primary" disabled title="Coming soon">
            Add Camera
          </button>
        }
      />
    </>
  );
}
