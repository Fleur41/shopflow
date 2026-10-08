/** Extract the opaque cursor from a DRF cursor-pagination "next" link. */
export function cursorFrom(next: string | null | undefined): string | undefined {
  if (!next) return undefined;
  return new URL(next, "http://placeholder").searchParams.get("cursor") ?? undefined;
}
