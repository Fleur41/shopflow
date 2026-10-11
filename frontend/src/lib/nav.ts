import { can } from "./auth";
import type { Me } from "./api/types";

export type NavItem = { href: string; label: string; permission?: string };

const ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard" },
  { href: "/products", label: "Products", permission: "products.view" },
  { href: "/settings/stores", label: "Stores", permission: "stores.view" },
  { href: "/settings/staff", label: "Staff", permission: "users.view" },
  { href: "/settings/roles", label: "Roles", permission: "roles.view" },
  { href: "/settings/catalog", label: "Catalog setup", permission: "products.manage" },
  { href: "/settings/payment-methods", label: "Payment methods", permission: "org.manage" },
];

/** Only show what the user may open; the server enforces it regardless. */
export function navItemsFor(me: Me | undefined): NavItem[] {
  return ITEMS.filter((item) => !item.permission || can(me, item.permission));
}
