import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Waitlist capture endpoint for the Caffe Steve marketing site.
 *
 * POST /api/waitlist
 *   body: { email: string; website?: string }
 *     - `email`   : required, validated.
 *     - `website` : honeypot. Real users never see/fill this. If present, we
 *                   silently pretend success and drop the request.
 *   -> 200 { ok: true }
 *   -> 400 { ok: false, error }
 *
 * GET  /api/waitlist -> 405 (method not allowed)
 *
 * Persistence is BEST-EFFORT: we append a line to `web/.waitlist.jsonl`.
 * TODO(production): swap the file append for a real store + transactional email.
 *   e.g. Supabase `waitlist` table insert, then Resend confirmation email:
 *     await supabase.from("waitlist").insert({ email, source: "landing" });
 *     await resend.emails.send({ to: email, ... });
 *   Also move rate-limiting to a shared store (Upstash Redis) — the in-memory
 *   map below is per-instance only and resets on cold start / deploy.
 */

export const runtime = "nodejs";

// Reasonably strict, pragmatic email check (RFC-perfect regexes are a trap).
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_LENGTH = 254;

// --- In-memory rate limit -------------------------------------------------
// NOTE: in-memory only. Resets on cold start and is NOT shared across serverless
// instances. Good enough to blunt casual abuse; use Upstash/Redis in prod.
const RATE_LIMIT_MAX = 5; // requests
const RATE_LIMIT_WINDOW_MS = 60_000; // per minute, per IP
const hits = new Map<string, { count: number; resetAt: number }>();

function isRateLimited(key: string): boolean {
  const now = Date.now();
  const entry = hits.get(key);
  if (!entry || now > entry.resetAt) {
    hits.set(key, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return false;
  }
  entry.count += 1;
  return entry.count > RATE_LIMIT_MAX;
}

function clientKey(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0]!.trim();
  return req.headers.get("x-real-ip") ?? "unknown";
}

type WaitlistBody = {
  email?: unknown;
  website?: unknown; // honeypot
};

export async function POST(req: Request): Promise<NextResponse> {
  if (isRateLimited(clientKey(req))) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please try again shortly." },
      { status: 429 },
    );
  }

  let body: WaitlistBody;
  try {
    body = (await req.json()) as WaitlistBody;
  } catch {
    return NextResponse.json(
      { ok: false, error: "Invalid request body." },
      { status: 400 },
    );
  }

  // Honeypot: if the hidden field is filled, it's a bot. Pretend success so we
  // don't tip them off, but persist nothing.
  if (typeof body.website === "string" && body.website.trim() !== "") {
    return NextResponse.json({ ok: true });
  }

  const email =
    typeof body.email === "string" ? body.email.trim().toLowerCase() : "";

  if (!email) {
    return NextResponse.json(
      { ok: false, error: "Email is required." },
      { status: 400 },
    );
  }
  if (email.length > MAX_EMAIL_LENGTH || !EMAIL_RE.test(email)) {
    return NextResponse.json(
      { ok: false, error: "Please enter a valid email address." },
      { status: 400 },
    );
  }

  // Best-effort persistence. Failure here must NOT break the user's signup.
  try {
    const record =
      JSON.stringify({ email, ts: new Date().toISOString() }) + "\n";
    const file = path.join(process.cwd(), ".waitlist.jsonl");
    await fs.appendFile(file, record, "utf8");
  } catch (err) {
    // Filesystem may be read-only (e.g. some serverless targets). Don't fail.
    console.log("[waitlist] persist failed, logging instead:", email, err);
  }

  return NextResponse.json({ ok: true });
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { ok: false, error: "Method not allowed." },
    { status: 405, headers: { Allow: "POST" } },
  );
}
