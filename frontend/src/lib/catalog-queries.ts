import { useQuery } from "@tanstack/react-query";

import { api } from "./api/client";
import { unwrap } from "./api/errors";
import { BRANDS_KEY, CATEGORIES_KEY, TAX_RATES_KEY, UNITS_KEY } from "./query-keys";

/**
 * Catalog lookups are short lists, loaded in one request (the API's largest
 * page). `activeOnly` lists are for choosing; the full lists are for setup.
 */
const ALL = 200;

function query(activeOnly: boolean) {
  return { page_size: ALL, ...(activeOnly ? { is_active: true } : {}) };
}

export function useCategories(activeOnly = false) {
  return useQuery({
    queryKey: [...CATEGORIES_KEY, { activeOnly }],
    queryFn: () => unwrap(api.GET("/api/v1/categories/", { params: { query: query(activeOnly) } })),
  });
}

export function useBrands(activeOnly = false) {
  return useQuery({
    queryKey: [...BRANDS_KEY, { activeOnly }],
    queryFn: () => unwrap(api.GET("/api/v1/brands/", { params: { query: query(activeOnly) } })),
  });
}

export function useUnits(activeOnly = false) {
  return useQuery({
    queryKey: [...UNITS_KEY, { activeOnly }],
    queryFn: () => unwrap(api.GET("/api/v1/units/", { params: { query: query(activeOnly) } })),
  });
}

export function useTaxRates(activeOnly = false) {
  return useQuery({
    queryKey: [...TAX_RATES_KEY, { activeOnly }],
    queryFn: () => unwrap(api.GET("/api/v1/tax-rates/", { params: { query: query(activeOnly) } })),
  });
}
