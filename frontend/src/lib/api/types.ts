import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Store = Schemas["Store"];
export type StoreSummary = Schemas["StoreSummary"];
export type Member = Schemas["Member"];
export type Role = Schemas["Role"];
export type PaymentMethod = Schemas["PaymentMethod"];
export type PaymentMethodKind = Schemas["PaymentMethodKind"];
export type EtimsPaymentType = Schemas["EtimsPaymentType"];
export type Category = Schemas["Category"];
export type Brand = Schemas["Brand"];
export type Unit = Schemas["Unit"];
export type TaxRate = Schemas["TaxRate"];
export type Product = Schemas["Product"];
export type ProductIdentifier = Schemas["ProductIdentifier"];
export type PriceHistory = Schemas["PriceHistory"];
