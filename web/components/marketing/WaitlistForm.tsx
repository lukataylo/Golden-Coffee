"use client";

import { useState, type FormEvent } from "react";

type Status = "idle" | "loading" | "success" | "error";

// Mirror of the server-side check so we can fail fast before a round-trip.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Waitlist capture. Client component: validates the email locally, POSTs
 * { email, website } to /api/waitlist, and renders inline success/error.
 * `website` is a honeypot — hidden from users, only bots fill it.
 */
export default function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string>("");

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setMessage("");

    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setStatus("error");
      setMessage("Please enter a valid email address.");
      return;
    }

    setStatus("loading");
    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed, website: honeypot }),
      });
      const data: { ok?: boolean; error?: string } = await res
        .json()
        .catch(() => ({}));

      if (res.ok && data.ok) {
        setStatus("success");
        setMessage("You're on the list. We'll be in touch soon.");
        setEmail("");
      } else {
        setStatus("error");
        setMessage(data.error ?? "Something went wrong. Please try again.");
      }
    } catch {
      setStatus("error");
      setMessage("Network error. Please try again.");
    }
  }

  const isLoading = status === "loading";

  return (
    <form onSubmit={onSubmit} noValidate className="w-full max-w-md">
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="flex-1">
          <label htmlFor="waitlist-email" className="sr-only">
            Email address
          </label>
          <input
            id="waitlist-email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            placeholder="you@yourcafe.com"
            value={email}
            disabled={isLoading || status === "success"}
            onChange={(e) => {
              setEmail(e.target.value);
              if (status === "error") {
                setStatus("idle");
                setMessage("");
              }
            }}
            aria-invalid={status === "error"}
            aria-describedby="waitlist-message"
            className="w-full rounded-xl border border-white/15 bg-white/[0.04] px-4 py-3 text-[#f4ece1] placeholder:text-white/35 outline-none transition focus:border-[#d9a441] focus:ring-2 focus:ring-[#d9a441]/40 disabled:opacity-60"
          />
        </div>

        {/* Honeypot — visually hidden, off-screen, not announced to AT. */}
        <div
          aria-hidden="true"
          className="absolute left-[-9999px] top-[-9999px] h-0 w-0 overflow-hidden"
        >
          <label htmlFor="website">Leave this field empty</label>
          <input
            id="website"
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </div>

        <button
          type="submit"
          disabled={isLoading || status === "success"}
          className="inline-flex items-center justify-center rounded-xl bg-[#d9a441] px-5 py-3 font-semibold text-[#0e0b08] transition hover:bg-[#e7b75a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441] disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isLoading
            ? "Requesting…"
            : status === "success"
              ? "Requested ✓"
              : "Request early access"}
        </button>
      </div>

      <p
        id="waitlist-message"
        role="status"
        aria-live="polite"
        className={`mt-2 min-h-[1.25rem] text-sm ${
          status === "error"
            ? "text-red-300"
            : status === "success"
              ? "text-[#d9a441]"
              : "text-white/45"
        }`}
      >
        {message ||
          "No spam. Just an invite when your venue is up next."}
      </p>
    </form>
  );
}
