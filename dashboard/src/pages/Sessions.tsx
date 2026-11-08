import { EmptyState } from "./EmptyState";

export function Sessions() {
  return (
    <>
      <h1>Sessions</h1>
      <EmptyState title="No sessions yet." body="Upload a training video to analyse your first session." />
    </>
  );
}
