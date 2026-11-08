import { EmptyState } from "./EmptyState";

export function LiveOperations() {
  return (
    <>
      <h1>Live Operations</h1>
      <EmptyState title="No active faults." body="Your site is operating normally." />
    </>
  );
}
