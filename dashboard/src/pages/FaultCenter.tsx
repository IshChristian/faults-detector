import { EmptyState } from "./EmptyState";

export function FaultCenter() {
  return (
    <>
      <h1>Fault Center</h1>
      <EmptyState title="No active faults." body="Your site is operating normally." />
    </>
  );
}
