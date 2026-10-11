"""KRA eTIMS code lists used by the catalog (docs/ETIMS.md).

A static copy of the lists in KRA's OSCU specification v2.0 (§4.1, 4.3,
4.6, 4.7). KRA publishes the live lists through ``selectCodeList``; from
3.8 the synced lists take over and these remain the fallback.
"""

from decimal import Decimal

# Tax type → (label, the rate it implies). A rate change by law means
# updating this table, which is why it isn't a database constraint.
TAX_TYPES: dict[str, tuple[str, Decimal]] = {
    "A": ("A · Exempt", Decimal("0")),
    "B": ("B · VAT 16%", Decimal("0.16")),
    "C": ("C · Zero-rated", Decimal("0")),
    "D": ("D · Non-VAT", Decimal("0")),
    "E": ("E · VAT 8%", Decimal("0.08")),
}

PRODUCT_TYPES = [
    ("1", "Raw material"),
    ("2", "Finished product"),
    ("3", "Service (no stock)"),
]

PACKAGING_UNITS = [
    ("AM", "Ampoule"), ("BA", "Barrel"), ("BC", "Bottle crate"), ("BE", "Bundle"),
    ("BF", "Balloon, non-protected"), ("BG", "Bag"), ("BJ", "Bucket"), ("BK", "Basket"),
    ("BL", "Bale"), ("BQ", "Bottle, protected cylindrical"), ("BR", "Bar"),
    ("BV", "Bottle, bulbous"), ("BZ", "Bag"), ("CA", "Can"), ("CH", "Chest"),
    ("CJ", "Coffin"), ("CL", "Coil"), ("CR", "Wooden box"), ("CS", "Cassette"),
    ("CT", "Carton"), ("CTN", "Container"), ("CY", "Cylinder"), ("DR", "Drum"),
    ("GT", "Extra countable item"), ("HH", "Hand baggage"), ("IZ", "Ingots"), ("JR", "Jar"),
    ("JU", "Jug"), ("JY", "Jerrycan, cylindrical"), ("KZ", "Canister"),
    ("LZ", "Logs, in bundle"), ("NT", "Net"), ("OU", "Non-exterior packaging unit"),
    ("PD", "Poddon"), ("PG", "Plate"), ("PI", "Pipe"), ("PO", "Pilot"), ("PU", "Tray pack"),
    ("RL", "Reel"), ("RO", "Roll"), ("RZ", "Rods, in bundle"), ("SK", "Skeleton case"),
    ("TY", "Tank, cylindrical"), ("VG", "Bulk, gas"), ("VL", "Bulk, liquid"),
    ("VO", "Bulk, solid, large particles"), ("VQ", "Bulk, liquefied gas"),
    ("VR", "Bulk, solid, granular particles"), ("VT", "Extra bulk item"),
    ("VY", "Bulk, fine particles"), ("ML", "Mills (cigarettes)"), ("TN", "TAN (20 bags)"),
]  # fmt: skip

QUANTITY_UNITS = [
    ("4B", "Pair"), ("AV", "Cap"), ("BA", "Barrel"), ("BE", "Bundle"), ("BG", "Bag"),
    ("BL", "Block"), ("BLL", "Barrel (petroleum)"), ("BX", "Box"), ("CA", "Can"),
    ("CEL", "Cell"), ("CMT", "Centimetre"), ("CR", "Carat"), ("DR", "Drum"), ("DZ", "Dozen"),
    ("GLL", "Gallon"), ("GRM", "Gram"), ("GRO", "Gross"), ("KG", "Kilogram"),
    ("KTM", "Kilometre"), ("KWT", "Kilowatt"), ("L", "Litre"), ("LBR", "Pound"),
    ("LK", "Link"), ("LTR", "Litre"), ("M", "Metre"), ("M2", "Square metre"),
    ("M3", "Cubic metre"), ("MGM", "Milligram"), ("MTR", "Metre"), ("MWT", "Megawatt hour"),
    ("NO", "Number"), ("NX", "Part per thousand"), ("PA", "Packet"), ("PG", "Plate"),
    ("PR", "Pair"), ("RL", "Reel"), ("RO", "Roll"), ("SET", "Set"), ("ST", "Sheet"),
    ("TNE", "Tonne"), ("TU", "Tube"), ("U", "Pieces / items"), ("YRD", "Yard"),
]  # fmt: skip

TAX_TYPE_CHOICES = [(code, label) for code, (label, _) in TAX_TYPES.items()]
