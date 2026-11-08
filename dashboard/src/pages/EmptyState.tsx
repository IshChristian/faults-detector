import type { ReactNode } from "react";

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <section className="card empty-state">
      <p className="empty-title">{title}</p>
      <p className="empty-body">{body}</p>
      {action}
    </section>
  );
}
