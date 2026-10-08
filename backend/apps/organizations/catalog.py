"""The permission catalog and default role templates (docs/SECURITY.md §3).

Permissions are defined here, in code, and synced to the database after every
``migrate``. Organizations get editable copies of the Manager and Cashier
templates; the Owner role is a system role that always holds every permission,
including ones added in later releases.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    description: str
    sensitive: bool = False  # holders need MFA (Phase 1.9); every use is audited

    @property
    def category(self) -> str:
        return self.code.split(".", 1)[0]


CATALOG: tuple[PermissionDef, ...] = (
    # Organization and stores
    PermissionDef("org.view", "View organization details"),
    PermissionDef("org.manage", "Edit organization settings and payment methods", sensitive=True),
    PermissionDef("stores.view", "View stores"),
    PermissionDef("stores.manage", "Create and edit stores", sensitive=True),
    PermissionDef(
        "stores.manage_inventory_policy",
        "Change negative-stock and offline policies",
        sensitive=True,
    ),
    # Users and roles
    PermissionDef("users.view", "View staff members"),
    PermissionDef("users.manage", "Add, edit and suspend staff members", sensitive=True),
    PermissionDef("roles.view", "View roles and permissions"),
    PermissionDef("roles.manage", "Create and edit roles", sensitive=True),
    # Catalog
    PermissionDef("products.view", "View products and prices"),
    PermissionDef("products.manage", "Create and edit products"),
    PermissionDef("products.change_price", "Change selling prices", sensitive=True),
    # Inventory
    PermissionDef("inventory.view", "View stock levels"),
    PermissionDef("inventory.view_movements", "View inventory movement history"),
    PermissionDef("inventory.manage_levels", "Set reorder, minimum and maximum levels"),
    PermissionDef("inventory.adjust", "Adjust stock (damage, counts, write-offs)", sensitive=True),
    PermissionDef("inventory.receive", "Receive stock"),
    # Sales
    PermissionDef("sales.create", "Make sales"),
    PermissionDef("sales.view_own", "View own sales"),
    PermissionDef("sales.view_all", "View all sales"),
    PermissionDef("sales.discount", "Give discounts within the role's limit"),
    PermissionDef("sales.override_price", "Override prices at the till", sensitive=True),
    PermissionDef("sales.credit", "Sell on customer credit"),
    PermissionDef("sales.void", "Void sales", sensitive=True),
    PermissionDef("sales.return", "Process returns and refunds", sensitive=True),
    # Cash control
    PermissionDef("cash.open_session", "Open a till session"),
    PermissionDef("cash.close_session", "Close a till session"),
    PermissionDef("cash.pay_in_out", "Record pay-ins, pay-outs and safe drops"),
    PermissionDef("cash.view_sessions", "View all till sessions and variances"),
    PermissionDef("cash.correct", "Record corrections on closed till sessions", sensitive=True),
    # Customers
    PermissionDef("customers.view", "View customers"),
    PermissionDef("customers.view_contact", "View customer phone, email and address"),
    PermissionDef("customers.create", "Add customers"),
    PermissionDef("customers.manage", "Edit and deactivate customers"),
    PermissionDef("customers.view_balance", "View customer balances and statements"),
    PermissionDef("customers.receive_payment", "Record customer payments"),
    PermissionDef(
        "customers.set_credit_limit", "Set credit limits and freeze accounts", sensitive=True
    ),
    PermissionDef("customers.exceed_credit_limit", "Sell beyond a credit limit", sensitive=True),
    PermissionDef("customers.reverse_entry", "Reverse customer ledger entries", sensitive=True),
    PermissionDef("customers.reconcile", "Reconcile customer accounts", sensitive=True),
    # Suppliers and purchasing
    PermissionDef("suppliers.view", "View suppliers"),
    PermissionDef("suppliers.manage", "Create and edit suppliers"),
    PermissionDef("purchasing.view", "View purchase orders and receipts"),
    PermissionDef("purchasing.create_po", "Create purchase orders"),
    PermissionDef("purchasing.receive", "Receive goods from suppliers"),
    PermissionDef("purchasing.return", "Return goods to suppliers"),
    PermissionDef("purchasing.view_payables", "View supplier balances"),
    PermissionDef("purchasing.pay_supplier", "Record supplier payments", sensitive=True),
    # Reports and audit
    PermissionDef("reports.view", "View reports"),
    PermissionDef("reports.view_customers", "View customer reports"),
    PermissionDef("reports.view_all_stores", "View organization-wide reports"),
    PermissionDef("audit.view", "View the audit log", sensitive=True),
    # Mobile sync
    PermissionDef("sync.register_device", "Register a mobile device"),
    PermissionDef("sync.resolve_conflicts", "Resolve offline sync conflicts", sensitive=True),
)

ALL_CODES: frozenset[str] = frozenset(p.code for p in CATALOG)

OWNER = "OWNER"
MANAGER = "MANAGER"
CASHIER = "CASHIER"

# Template roles copied into every new organization: (name, description, codes).
ROLE_TEMPLATES: dict[str, tuple[str, str, frozenset[str]]] = {
    MANAGER: (
        "Manager",
        "Runs day-to-day operations: stock, sales corrections, staff tills.",
        frozenset(
            {
                "org.view",
                "stores.view",
                "users.view",
                "roles.view",
                "products.view",
                "products.manage",
                "products.change_price",
                "inventory.view",
                "inventory.view_movements",
                "inventory.manage_levels",
                "inventory.adjust",
                "inventory.receive",
                "sales.create",
                "sales.view_own",
                "sales.view_all",
                "sales.discount",
                "sales.override_price",
                "sales.credit",
                "sales.void",
                "sales.return",
                "cash.open_session",
                "cash.close_session",
                "cash.pay_in_out",
                "cash.view_sessions",
                "customers.view",
                "customers.view_contact",
                "customers.create",
                "customers.manage",
                "customers.view_balance",
                "customers.receive_payment",
                "suppliers.view",
                "suppliers.manage",
                "purchasing.view",
                "purchasing.create_po",
                "purchasing.receive",
                "purchasing.return",
                "purchasing.view_payables",
                "reports.view",
                "reports.view_customers",
                "sync.register_device",
                "sync.resolve_conflicts",
            }
        ),
    ),
    CASHIER: (
        "Cashier",
        "Sells, takes payments and receives stock at assigned stores.",
        frozenset(
            {
                "org.view",
                "stores.view",
                "products.view",
                "inventory.view",
                "inventory.receive",
                "sales.create",
                "sales.view_own",
                "sales.credit",
                "cash.open_session",
                "cash.close_session",
                "cash.pay_in_out",
                "customers.view",
                "customers.create",
                "customers.view_balance",
                "customers.receive_payment",
                "sync.register_device",
            }
        ),
    ),
}
OWNER_ROLE_NAME = "Owner"
OWNER_ROLE_DESCRIPTION = "Full control of the business, including staff, roles and settings."

_unknown = set().union(*(codes for _, _, codes in ROLE_TEMPLATES.values())) - ALL_CODES
if _unknown:  # pragma: no cover - guards against typos when editing templates
    raise ValueError(f"Role templates reference unknown permissions: {sorted(_unknown)}")
