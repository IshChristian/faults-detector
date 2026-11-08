export type Role = "super_admin" | "customer_admin" | "operator" | "viewer";

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  customer_id: string | null;
  customer_industry: string | null;
};

/** Operators are called "Coach" for sports customers (V1 spec §5). */
export function roleLabel(user: Pick<User, "role" | "customer_industry">): string {
  switch (user.role) {
    case "super_admin":
      return "Super admin";
    case "customer_admin":
      return "Admin";
    case "operator":
      return user.customer_industry === "sports" ? "Coach" : "Operator";
    case "viewer":
      return "Viewer";
  }
}

export function homePath(user: Pick<User, "customer_industry">): string {
  return user.customer_industry === "sports" ? "/sessions" : "/live";
}
