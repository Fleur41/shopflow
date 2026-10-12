"""Create a demo business to click around in locally (``make seed``).

Goes through the same services as the API, so codes, price history and the
audit log look exactly as they would after real use. Refuses to run unless
DEBUG is on. Running it again only adds what's missing (matched by name), so
growing the lists below and re-running updates an existing demo business:
new products get opening stock, new customers are added, and sample sales are
made only if the business has none.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog import products
from apps.catalog.models import Brand, Category, Product, TaxRate, UnitOfMeasure
from apps.customers import services as customer_services
from apps.customers.models import Customer
from apps.inventory import services as inventory
from apps.inventory.models import StockLevel
from apps.organizations import master_data, services
from apps.organizations.context import RequestContext, role_permissions
from apps.organizations.master_data import MasterData
from apps.organizations.models import Membership, Organization, Role, Store
from apps.payments.models import PaymentMethod
from apps.sales import services as sales
from apps.sales.models import Sale
from apps.suppliers import services as suppliers
from apps.suppliers.models import ProductSupplier, Supplier

OWNER_EMAIL = "owner@demo.example"
ORGANIZATION_NAME = "Mama Njeri Supermarket"
PASSWORD = "shopflow-demo"  # noqa: S105 - local demo only; the command refuses without DEBUG
SERVICES = "Services"

# Name, category, brand, unit, tax rate, selling price, cost.
# Branded items get a barcode, numbered in list order: only ever append.
PRODUCTS = [
    ("Pishori Rice 2kg", "Groceries", "Daawat", "PCS", "Exempt", "420", "355"),
    ("Pishori Rice (loose)", "Groceries", None, "KG", "Exempt", "190", "160"),
    ("Maize Flour 2kg", "Groceries", "Jogoo", "PCS", "Exempt", "175", "152"),
    ("Wheat Flour 2kg", "Groceries", "Exe", "PCS", "Zero-rated", "210", "184"),
    ("Sugar 1kg", "Groceries", "Mumias", "PCS", "VAT 16%", "180", "158"),
    ("Cooking Oil 1L", "Groceries", "Fresh Fri", "PCS", "VAT 16%", "340", "298"),
    ("Fresh Milk 500ml", "Dairy", "Brookside", "PCS", "Exempt", "65", "55"),
    ("Yoghurt 500ml", "Dairy", "Brookside", "PCS", "VAT 16%", "150", "121"),
    ("Drinking Water 1L", "Beverages", "Keringet", "PCS", "VAT 16%", "70", "48"),
    ("Soda 500ml", "Beverages", "Coca-Cola", "PCS", "VAT 16%", "80", "62"),
    ("Tea Leaves 250g", "Beverages", "Ketepa", "PCS", "VAT 16%", "160", "132"),
    ("Bar Soap 800g", "Household", "Menengai", "PCS", "VAT 16%", "230", "196"),
    ("Washing Powder 1kg", "Household", "Omo", "PCS", "VAT 16%", "395", "340"),
    ("Toothpaste 100ml", "Personal care", "Colgate", "PCS", "VAT 16%", "185", "150"),
    ("Paraffin (per litre)", "Household", None, "L", "VAT 8%", "155", "141"),
    # Groceries
    ("Cooking Oil 3L", "Groceries", "Fresh Fri", "PCS", "VAT 16%", "980", "870"),
    ("Cooking Fat 1kg", "Groceries", "Kasuku", "PCS", "VAT 16%", "360", "318"),
    ("Pishori Rice 5kg", "Groceries", "Daawat", "PCS", "Exempt", "1020", "890"),
    ("Salt 1kg", "Groceries", "Kensalt", "PCS", "VAT 16%", "45", "34"),
    ("Spaghetti 400g", "Groceries", "Santa Lucia", "PCS", "VAT 16%", "120", "98"),
    ("Tomato Paste 70g", "Groceries", "Zesta", "PCS", "VAT 16%", "50", "38"),
    ("Beans (loose)", "Groceries", None, "KG", "Exempt", "160", "130"),
    ("Green Grams (loose)", "Groceries", None, "KG", "Exempt", "220", "185"),
    # Dairy and eggs
    ("Long Life Milk 500ml", "Dairy", "Brookside", "PCS", "Exempt", "75", "62"),
    ("Butter 250g", "Dairy", "KCC", "PCS", "VAT 16%", "380", "330"),
    ("Mala 500ml", "Dairy", "KCC", "PCS", "VAT 16%", "90", "72"),
    ("Eggs (tray of 30)", "Dairy", None, "PCS", "Exempt", "480", "420"),
    # Bakery
    ("White Bread 400g", "Bakery", "Supa Loaf", "PCS", "Zero-rated", "65", "55"),
    ("Brown Bread 400g", "Bakery", "Festive", "PCS", "Zero-rated", "70", "58"),
    ("Mandazi (each)", "Bakery", None, "PCS", "VAT 16%", "20", "12"),
    # Beverages
    ("Drinking Water 5L", "Beverages", "Keringet", "PCS", "VAT 16%", "230", "170"),
    ("Soda 2L", "Beverages", "Coca-Cola", "PCS", "VAT 16%", "220", "180"),
    ("Juice 1L", "Beverages", "Pick n Peel", "PCS", "VAT 16%", "270", "220"),
    ("Instant Coffee 50g", "Beverages", "Nescafé", "PCS", "VAT 16%", "350", "295"),
    ("Drinking Chocolate 200g", "Beverages", "Cadbury", "PCS", "VAT 16%", "420", "360"),
    # Snacks and sweets
    ("Crisps 100g", "Snacks", "Tropical Heat", "PCS", "VAT 16%", "110", "85"),
    ("Biscuits 200g", "Snacks", "Nuvita", "PCS", "VAT 16%", "75", "60"),
    ("Chocolate Bar 40g", "Snacks", "Cadbury", "PCS", "VAT 16%", "140", "112"),
    ("Roasted Peanuts 50g", "Snacks", "Nutpak", "PCS", "VAT 16%", "30", "22"),
    ("Chewing Gum", "Snacks", "Orbit", "PCS", "VAT 16%", "10", "6"),
    # Household
    ("Dishwashing Liquid 500ml", "Household", "Sunlight", "PCS", "VAT 16%", "210", "175"),
    ("Bleach 750ml", "Household", "Jik", "PCS", "VAT 16%", "175", "140"),
    ("Toilet Paper (10 pack)", "Household", "Rosy", "PCS", "VAT 16%", "520", "445"),
    ("Insect Spray 300ml", "Household", "Doom", "PCS", "VAT 16%", "450", "380"),
    ("Gas Refill 6kg", "Household", "K-Gas", "PCS", "VAT 16%", "1300", "1150"),
    ("Matchbox", "Household", None, "PCS", "VAT 16%", "5", "3"),
    ("Charcoal (per kg)", "Household", None, "KG", "VAT 16%", "60", "40"),
    # Personal care
    ("Bathing Soap 175g", "Personal care", "Geisha", "PCS", "VAT 16%", "85", "68"),
    ("Body Lotion 400ml", "Personal care", "Nivea", "PCS", "VAT 16%", "650", "545"),
    ("Petroleum Jelly 250g", "Personal care", "Vaseline", "PCS", "VAT 16%", "290", "240"),
    ("Shampoo 400ml", "Personal care", "Sunsilk", "PCS", "VAT 16%", "480", "400"),
    ("Sanitary Pads (8 pack)", "Personal care", "Always", "PCS", "Exempt", "120", "95"),
    ("Toothbrush", "Personal care", "Colgate", "PCS", "VAT 16%", "100", "75"),
    # Baby
    ("Diapers Size 3 (44 pack)", "Baby", "Huggies", "PCS", "VAT 16%", "1850", "1620"),
    ("Baby Wipes (72 pack)", "Baby", "Huggies", "PCS", "VAT 16%", "350", "290"),
    ("Baby Lotion 200ml", "Baby", "Johnson's", "PCS", "VAT 16%", "420", "350"),
    # Fresh produce
    ("Tomatoes", "Fresh produce", None, "KG", "Exempt", "120", "80"),
    ("Onions", "Fresh produce", None, "KG", "Exempt", "140", "95"),
    ("Potatoes", "Fresh produce", None, "KG", "Exempt", "90", "60"),
    ("Bananas", "Fresh produce", None, "KG", "Exempt", "100", "65"),
    ("Sukuma Wiki (bunch)", "Fresh produce", None, "PCS", "Exempt", "20", "12"),
    ("Avocado (each)", "Fresh produce", None, "PCS", "Exempt", "30", "18"),
    # Services: no stock, no barcode.
    ("Delivery within 5km", SERVICES, None, "PCS", "VAT 16%", "150", None),
]

# Price changes made after a product is created, so price history isn't empty.
PRICE_CHANGES = {"Sugar 1kg": "195", "Cooking Oil 3L": "1020", "Maize Flour 2kg": "165"}

# Name, KRA PIN, phone, email, payment terms, lead time, contacts, products (first
# listed supplier of a product becomes its preferred one).
SUPPLIERS: list[tuple[str, str, str, str, int, int, list[tuple[str, str, str]], list[str]]] = [
    (
        "Bidco Distributors",
        "P051234567B",
        "+254 20 444 5555",
        "orders@bidco.example",
        30,
        3,
        [("Grace Wanjiru", "Sales rep", "+254 712 000 111")],
        [
            "Cooking Oil 1L",
            "Cooking Oil 3L",
            "Cooking Fat 1kg",
            "Bar Soap 800g",
            "Washing Powder 1kg",
            "Dishwashing Liquid 500ml",
        ],
    ),
    (
        "Nairobi Grain Millers",
        "P052345678M",
        "+254 722 000 222",
        "sales@grainmillers.example",
        14,
        2,
        [("Peter Otieno", "Accounts", "+254 722 000 223")],
        [
            "Pishori Rice 2kg",
            "Pishori Rice 5kg",
            "Pishori Rice (loose)",
            "Maize Flour 2kg",
            "Wheat Flour 2kg",
            "Beans (loose)",
            "Green Grams (loose)",
        ],
    ),
    (
        "Brookside Dairy Depot",
        "",
        "+254 733 000 333",
        "",
        0,
        1,
        [("Faith Achieng", "Driver", "+254 733 000 334")],
        ["Fresh Milk 500ml", "Yoghurt 500ml", "Long Life Milk 500ml", "Butter 250g"],
    ),
    (
        "Westlands KCC Depot",
        "P053456789K",
        "+254 711 000 444",
        "depot@kcc-westlands.example",
        7,
        1,
        [("Samuel Mutua", "Depot manager", "+254 711 000 445")],
        ["Mala 500ml", "Butter 250g"],
    ),
    (
        "Rift Valley Beverages",
        "P054567890R",
        "+254 720 000 555",
        "orders@rvbeverages.example",
        21,
        3,
        [
            ("Mercy Chebet", "Sales rep", "+254 720 000 556"),
            ("Daniel Kiprop", "Accounts", "+254 720 000 557"),
        ],
        ["Drinking Water 1L", "Drinking Water 5L", "Soda 500ml", "Soda 2L", "Juice 1L"],
    ),
    (
        "Mombasa Road Wholesalers",
        "P055678901W",
        "+254 709 000 666",
        "sales@mombasaroad.example",
        30,
        5,
        [("Hassan Abdi", "Sales", "+254 709 000 667")],
        [
            "Sugar 1kg",
            "Salt 1kg",
            "Spaghetti 400g",
            "Tomato Paste 70g",
            "Tea Leaves 250g",
            "Instant Coffee 50g",
            "Drinking Chocolate 200g",
            "Crisps 100g",
            "Biscuits 200g",
            "Chocolate Bar 40g",
            "Roasted Peanuts 50g",
            "Chewing Gum",
            "Bleach 750ml",
            "Toilet Paper (10 pack)",
            "Insect Spray 300ml",
            "Matchbox",
            "Bathing Soap 175g",
            "Body Lotion 400ml",
            "Petroleum Jelly 250g",
            "Shampoo 400ml",
            "Sanitary Pads (8 pack)",
            "Toothpaste 100ml",
            "Toothbrush",
            "Cooking Oil 1L",  # a second source; Bidco stays preferred
        ],
    ),
    (
        "Kilimani Bakery Supplies",
        "",
        "+254 701 000 777",
        "",
        0,
        1,
        [("Esther Nyambura", "Owner", "+254 701 000 778")],
        ["White Bread 400g", "Brown Bread 400g", "Mandazi (each)", "Eggs (tray of 30)"],
    ),
    (
        "Gikomba Fresh Produce",
        "",
        "+254 790 000 888",
        "",
        0,
        1,
        [("Mama Atieno", "Owner", "+254 790 000 889")],
        ["Tomatoes", "Onions", "Potatoes", "Bananas", "Sukuma Wiki (bunch)", "Avocado (each)"],
    ),
    (
        "Safi Baby Care Distributors",
        "P056789012S",
        "+254 740 000 999",
        "orders@safibaby.example",
        30,
        4,
        [("Lucy Wambua", "Sales rep", "+254 740 001 000")],
        ["Diapers Size 3 (44 pack)", "Baby Wipes (72 pack)", "Baby Lotion 200ml"],
    ),
    (
        "Embakasi Gas Centre",
        "P057890123G",
        "+254 702 001 111",
        "",
        0,
        1,
        [("John Mwangi", "Owner", "+254 702 001 112")],
        ["Gas Refill 6kg", "Paraffin (per litre)", "Charcoal (per kg)"],
    ),
]


# Opening stock: most items get a default by unit; these are low or out, so the
# stock screen has something to flag. Westlands holds half as much.
STOCK_DEFAULTS = {"PCS": 36, "KG": 50, "L": 60}
STOCK_OVERRIDES = {
    "Butter 250g": 3,
    "Diapers Size 3 (44 pack)": 2,
    "Gas Refill 6kg": 4,
    "Eggs (tray of 30)": 5,
    "Chewing Gum": 0,
}

# Name, phone, credit limit (None: cash only), what they already owed.
CUSTOMERS = [
    ("Grace Akinyi", "+254712345678", "5000", "1250"),
    ("Kamau Hardware", "+254722111222", "20000", "4500"),
    ("Otieno Family", "+254733444555", "3000", None),
    ("Wanjiku Salon", "+254701222333", None, None),
]

# Sample sales at Kawangware: (items, how paid). Paid: "cash", "mpesa", "split" or a
# customer name for credit.
SALES: list[tuple[list[tuple[str, str]], str]] = [
    ([("Fresh Milk 500ml", "2"), ("White Bread 400g", "1")], "cash"),
    ([("Sugar 1kg", "2"), ("Cooking Oil 1L", "1")], "mpesa"),
    ([("Maize Flour 2kg", "2"), ("Sugar 1kg", "1"), ("Tea Leaves 250g", "1")], "Otieno Family"),
    ([("Pishori Rice 2kg", "1"), ("Tomatoes", "1.5"), ("Onions", "0.5")], "split"),
    ([("Soda 500ml", "3"), ("Crisps 100g", "2")], "cash"),
]


def with_check_digit(body: str) -> str:
    """Append the GTIN check digit (mod 10, weights 3/1 from the right)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str(-total % 10)


class Command(BaseCommand):
    help = "Create or top up a demo business with stores, staff, products and suppliers."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG on; it creates known passwords.")
        self.added: dict[str, int] = {}
        with transaction.atomic():
            self._seed()
        summary = ", ".join(f"{n} {what}" for what, n in self.added.items() if n) or "nothing"
        self.stdout.write(
            self.style.SUCCESS(f"Demo business ready (added {summary}).")
            + f"\n  Owner:   {OWNER_EMAIL}"
            + "\n  Manager: manager@demo.example"
            + "\n  Cashier: cashier@demo.example (Westlands only)"
            + f"\n  Password for all three: {PASSWORD}"
        )

    def _count(self, what: str) -> None:
        self.added[what] = self.added.get(what, 0) + 1

    def _seed(self) -> None:
        ctx = self._business()
        org = ctx.organization
        self._staff(ctx)

        units = {u.code: u for u in UnitOfMeasure.objects.for_org(org)}
        rates = {r.name: r for r in TaxRate.objects.for_org(org)}
        by_name: dict[str, Product] = {}
        barcode_number = 0
        for name, category, brand, unit, rate, price, cost in PRODUCTS:
            if brand:
                barcode_number += 1
            existing = Product.objects.for_org(org).filter(name__iexact=name).first()
            if existing:
                by_name[name] = existing
                continue
            service = category == SERVICES
            product = products.create_product(
                ctx,
                name=name,
                category=self._named(ctx, Category, category),
                brand=self._named(ctx, Brand, brand) if brand else None,
                unit=units[unit],
                tax_rate=rates[rate],
                selling_price=Decimal(price),
                default_cost=Decimal(cost) if cost else None,
                default_reorder_level=None if service else Decimal(10 if unit == "PCS" else 20),
                track_inventory=not service,
                etims_product_type="3" if service else "2",
                identifiers=(
                    [{"value": with_check_digit(f"6161{barcode_number:08d}")}] if brand else []
                ),
            )
            self._count("products")
            if name in PRICE_CHANGES:
                product = products.update_product(
                    ctx,
                    product,
                    version=product.version,
                    selling_price=Decimal(PRICE_CHANGES[name]),
                )
            by_name[name] = product

        for name, pin, phone, email, terms, lead_time, contacts, supplied in SUPPLIERS:
            supplier = Supplier.objects.for_org(org).filter(name__iexact=name).first()
            if supplier is None:
                supplier = suppliers.create_supplier(
                    ctx,
                    name=name,
                    kra_pin=pin,
                    phone=phone.replace(" ", ""),
                    email=email,
                    payment_terms_days=terms,
                )
                self._count("suppliers")
                for contact_name, title, contact_phone in contacts:
                    suppliers.add_contact(
                        ctx,
                        supplier,
                        name=contact_name,
                        role_title=title,
                        phone=contact_phone.replace(" ", ""),
                    )
            linked = set(
                ProductSupplier.objects.for_org(org)
                .filter(supplier=supplier)
                .values_list("product_id", flat=True)
            )
            for product_name in supplied:
                product = by_name[product_name]
                if product.pk not in linked:
                    suppliers.link_product(
                        ctx, product=product, supplier=supplier, lead_time_days=lead_time
                    )
                    self._count("supplier links")

        self._stock(ctx, by_name)
        self._customers(ctx)
        self._sales(ctx, by_name)

    def _stock(self, ctx: RequestContext, by_name: dict[str, Product]) -> None:
        """Opening stock for every stocked product that has no history in a store yet."""
        for store, share in self._stores(ctx):
            started = set(
                StockLevel.objects.for_org(ctx.organization)
                .filter(store=store, last_movement_seq__gt=0)
                .values_list("product_id", flat=True)
            )
            lines = []
            for name, product in by_name.items():
                if not product.track_inventory or product.pk in started:
                    continue
                full = STOCK_OVERRIDES.get(name, STOCK_DEFAULTS[product.unit.code])
                quantity = Decimal(full * share // 100)
                lines.append(
                    inventory.AdjustmentLineInput(
                        product=product,
                        counted_quantity=quantity,
                        unit_cost=product.default_cost if quantity else None,
                    )
                )
            if lines:
                inventory.create_adjustment(
                    ctx,
                    store,
                    client_txn_id=uuid.uuid4(),
                    reason_code="OPENING_BALANCE",
                    lines=lines,
                )
                self.added["opening stock lines"] = self.added.get("opening stock lines", 0) + len(
                    lines
                )

    def _stores(self, ctx: RequestContext) -> list[tuple[Store, int]]:
        stores = Store.objects.for_org(ctx.organization)
        return [(stores.get(code="MAIN"), 100), (stores.get(code="WST"), 50)]

    def _customers(self, ctx: RequestContext) -> None:
        for name, phone, limit, owed in CUSTOMERS:
            if Customer.objects.for_org(ctx.organization).filter(name__iexact=name).exists():
                continue
            customer = customer_services.create_customer(
                ctx, name=name, phone=phone, credit_limit=Decimal(limit) if limit else None
            )
            self._count("customers")
            if owed:
                customer_services.set_opening_balance(
                    ctx, customer, amount=Decimal(owed), note="From the old credit book"
                )

    def _sales(self, ctx: RequestContext, by_name: dict[str, Product]) -> None:
        """A few sales so the sales list, receipts and stock history aren't empty.
        Only on a business that hasn't sold anything yet."""
        if Sale.objects.for_org(ctx.organization).exists():
            return
        store = Store.objects.for_org(ctx.organization).get(code="MAIN")
        methods = {m.code: m for m in PaymentMethod.objects.for_org(ctx.organization)}
        now = timezone.now()
        for index, (lines, paid) in enumerate(SALES):
            items = [
                sales.ItemInput(by_name[name], Decimal(quantity), by_name[name].selling_price)
                for name, quantity in lines
            ]
            total = sum(
                ((item.quantity * item.unit_price).quantize(Decimal("0.01")) for item in items),
                Decimal(0),
            )
            tenders: list[sales.TenderInput] = []
            customer = None
            credit = Decimal(0)
            if paid == "cash":
                tendered = (total / 100).to_integral_value(rounding="ROUND_CEILING") * 100
                tenders = [sales.TenderInput(methods["CASH"], total, tendered=tendered)]
            elif paid == "mpesa":
                tenders = [
                    sales.TenderInput(methods["MPESA"], total, reference=f"SEED{index}A2B3C")
                ]
            elif paid == "split":
                tenders = [
                    sales.TenderInput(methods["CASH"], Decimal(100)),
                    sales.TenderInput(methods["MPESA"], total - 100, reference=f"SEED{index}D4E5F"),
                ]
            else:
                customer = Customer.objects.for_org(ctx.organization).get(name=paid)
                credit = total
            sales.create_sale(
                ctx,
                store,
                sales.SaleRequest(
                    client_txn_id=uuid.uuid4(),
                    items=items,
                    tenders=tenders,
                    customer=customer,
                    credit_amount=credit,
                    occurred_at=now - timedelta(hours=len(SALES) - index),
                ),
            )
            self._count("sales")

    def _business(self) -> RequestContext:
        """The demo owner's context, registering the business on the first run."""
        membership = (
            Membership.unscoped.filter(
                user__email=OWNER_EMAIL, organization__name=ORGANIZATION_NAME
            )
            .select_related("user", "organization", "role")
            .first()
        )
        if membership is None:
            if User.objects.filter(email=OWNER_EMAIL).exists():
                raise CommandError(f"{OWNER_EMAIL} exists but doesn't own {ORGANIZATION_NAME}.")
            membership = services.register_business(
                email=OWNER_EMAIL,
                full_name="Wambui Njeri",
                password=PASSWORD,
                organization_name=ORGANIZATION_NAME,
                currency="KES",
                timezone="Africa/Nairobi",
                store_name="Kawangware",
            ).membership
            self._count("business")
        return _context(membership)

    def _staff(self, ctx: RequestContext) -> None:
        org = ctx.organization
        westlands = Store.objects.for_org(org).filter(code="WST").first()
        if westlands is None:
            westlands = services.create_store(
                ctx, code="WST", name="Westlands", address="Woodvale Grove", phone="+254700000002"
            )
            self._count("stores")
        roles = {r.template: r for r in Role.objects.for_org(org)}
        staff = [
            ("manager@demo.example", "Joseph Kamau", Role.Template.MANAGER, True, []),
            ("cashier@demo.example", "Akinyi Odhiambo", Role.Template.CASHIER, False, [westlands]),
        ]
        for email, full_name, template, all_stores, stores in staff:
            if Membership.objects.for_org(org).filter(user__email=email).exists():
                continue
            services.add_member(
                ctx,
                email=email,
                full_name=full_name,
                password=PASSWORD,
                role=roles[template],
                all_stores=all_stores,
                stores=stores,
            )
            self._count("staff")
        # Skip the "confirm your email" nudge: these addresses can't receive mail.
        User.objects.filter(email__endswith="@demo.example", email_verified_at=None).update(
            email_verified_at=timezone.now()
        )

    def _named[E: MasterData](self, ctx: RequestContext, model: type[E], name: str) -> E:
        """The category or brand called ``name``, created if it doesn't exist yet."""
        entry = model.objects.for_org(ctx.organization).filter(name__iexact=name).first()
        if entry is None:
            entry = master_data.create_entry(ctx, model, name=name)
            self._count("categories" if model is Category else "brands")
        return entry


def _context(membership: Membership) -> RequestContext:
    """Act as the owner, as if signed in with two-step verification."""
    organization: Organization = membership.organization
    return RequestContext(
        user=membership.user,
        organization=organization,
        membership=membership,
        role=membership.role,
        permissions=role_permissions(membership.role),
        store_ids=frozenset(),
        session_id=membership.pk,
        mfa_verified=True,
        request_id="seed",
        ip_address=None,
        user_agent="seed_demo",
    )
