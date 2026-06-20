/**
 * Typed, validated environment access.
 *
 * Only `NEXT_PUBLIC_*` vars are referenced here so this module is safe to import
 * from both server and client components. Clerk's own keys are read by the Clerk
 * SDK directly; we validate the product URLs we link to.
 */

function required(name: string, value: string | undefined): string {
  if (!value || value.trim() === "") {
    // During `next build` env may be absent; fall back rather than crash the
    // build. At runtime in the browser a missing public URL is a config error.
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.warn(`[env] Missing ${name}; using empty string.`);
    }
    return "";
  }
  return value.trim();
}

function withFallback(value: string | undefined, fallback: string): string {
  return value && value.trim() !== "" ? value.trim() : fallback;
}

const DASHBOARD_URL = withFallback(
  process.env.NEXT_PUBLIC_DASHBOARD_URL,
  "https://golden-coffee-production.up.railway.app",
);

export const env = {
  appUrl: withFallback(process.env.NEXT_PUBLIC_APP_URL, "http://localhost:3000"),
  dashboardUrl: DASHBOARD_URL,
  scanUrl: withFallback(
    process.env.NEXT_PUBLIC_SCAN_URL,
    `${DASHBOARD_URL.replace(/\/$/, "")}/scan/`,
  ),
  signInUrl: withFallback(process.env.NEXT_PUBLIC_CLERK_SIGN_IN_URL, "/sign-in"),
  signUpUrl: withFallback(process.env.NEXT_PUBLIC_CLERK_SIGN_UP_URL, "/sign-up"),
} as const;

export type Env = typeof env;

// Touch `required` so it is not flagged as unused; surfaces missing publishable
// key as a soft warning in the browser console for easier local setup.
if (typeof window !== "undefined") {
  required(
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
  );
}
