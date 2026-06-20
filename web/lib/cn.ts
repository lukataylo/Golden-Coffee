/**
 * Tiny className combiner. Filters out falsy values and joins with a space.
 * Keeps the dependency footprint minimal (no clsx/tailwind-merge needed here).
 */
export type ClassValue = string | number | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
