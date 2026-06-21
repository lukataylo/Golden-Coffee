import { NextResponse } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

/**
 * Public routes — everything else (the `(app)` route group: /onboarding,
 * /dashboard, …) requires an authenticated session.
 */
const isPublicRoute = createRouteMatcher([
  "/",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/api/waitlist(.*)",
]);

const clerkEnabled = !!(
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY.trim()
);

// With Clerk configured, protect the app routes. Without a key, pass everything
// through so the site runs zero-config (clerkMiddleware would otherwise throw).
export default clerkEnabled
  ? clerkMiddleware(async (auth, request) => {
      if (!isPublicRoute(request)) {
        await auth.protect();
      }
    })
  : () => NextResponse.next();

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes.
    "/(api|trpc)(.*)",
  ],
};
