import {
  Boxes,
  Contact,
  CreditCard,
  LayoutDashboard,
  type LucideIcon,
  Package,
  ReceiptText,
  ScanBarcode,
  Shapes,
  ShieldCheck,
  Store,
  Truck,
  Users,
  Vault,
} from "lucide-react";

import { can } from "./auth";
import type { Me } from "./api/types";

export type NavGroup = "Overview" | "Selling" | "Catalog" | "Buying" | "Business";
export type NavItem = { href: string; label: string; group: NavGroup; icon: LucideIcon; permission?: string };

const ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", group: "Overview", icon: LayoutDashboard },
  { href: "/sell", label: "Sell", group: "Selling", icon: ScanBarcode, permission: "sales.create" },
  { href: "/sales", label: "Sales", group: "Selling", icon: ReceiptText, permission: "sales.view_own" },
  { href: "/customers", label: "Customers", group: "Selling", icon: Contact, permission: "customers.view" },
  { href: "/cash", label: "Till sessions", group: "Selling", icon: Vault, permission: "cash.view_sessions" },
  { href: "/products", label: "Products", group: "Catalog", icon: Package, permission: "products.view" },
  { href: "/inventory", label: "Stock", group: "Catalog", icon: Boxes, permission: "inventory.view" },
  { href: "/settings/catalog", label: "Catalog setup", group: "Catalog", icon: Shapes, permission: "products.manage" },
  { href: "/suppliers", label: "Suppliers", group: "Buying", icon: Truck, permission: "suppliers.view" },
  { href: "/settings/stores", label: "Stores", group: "Business", icon: Store, permission: "stores.view" },
  { href: "/settings/staff", label: "Staff", group: "Business", icon: Users, permission: "users.view" },
  { href: "/settings/roles", label: "Roles", group: "Business", icon: ShieldCheck, permission: "roles.view" },
  { href: "/settings/payment-methods", label: "Payment methods", group: "Business", icon: CreditCard, permission: "org.manage" },
];

/** Only show what the user may open; the server enforces it regardless. */
export function navItemsFor(me: Me | undefined): NavItem[] {
  return ITEMS.filter((item) => !item.permission || can(me, item.permission));
}

/** The visible items, grouped in menu order. */
export function navGroupsFor(me: Me | undefined): { group: NavGroup; items: NavItem[] }[] {
  const groups: { group: NavGroup; items: NavItem[] }[] = [];
  for (const item of navItemsFor(me)) {
    const last = groups.at(-1);
    if (last?.group === item.group) last.items.push(item);
    else groups.push({ group: item.group, items: [item] });
  }
  return groups;
}
