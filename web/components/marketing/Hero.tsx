import AuroraBackground from "./AuroraBackground";
import Wordmark from "./Wordmark";
import WaitlistForm from "./WaitlistForm";

const DEMO_URL = "https://golden-coffee-production.up.railway.app";

export default function Hero() {
  return (
    <header className="relative isolate overflow-hidden">
      <AuroraBackground />

      {/* Top nav */}
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Wordmark />
        <a
          href="/sign-in"
          className="rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:text-[#f4ece1] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441]"
        >
          Sign in
        </a>
      </nav>

      {/* Hero body */}
      <div className="mx-auto flex max-w-3xl flex-col items-center px-6 pb-24 pt-16 text-center sm:pt-24">
        {/* Coming soon badge */}
        <span className="gc-fade-up mb-8 inline-flex items-center gap-2 rounded-full border border-[#d9a441]/30 bg-[#d9a441]/10 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-[#d9a441]">
          <span className="gc-pulse-dot h-1.5 w-1.5 rounded-full bg-[#d9a441]" />
          Coming soon
        </span>

        <h1
          className="gc-fade-up text-balance text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl"
          style={{ animationDelay: "60ms" }}
        >
          Your café,{" "}
          <span className="bg-gradient-to-r from-[#d9a441] to-[#e7b75a] bg-clip-text text-transparent">
            but it runs itself
          </span>
        </h1>

        <p
          className="gc-fade-up mt-6 max-w-xl text-pretty text-lg leading-relaxed text-white/65"
          style={{ animationDelay: "120ms" }}
        >
          Coffee Steve turns a single existing camera into an ambient + ops
          copilot that reads the room and quietly tunes music, lighting, scent
          and temperature — while protecting your speed-of-service.
        </p>

        {/* Waitlist */}
        <div
          className="gc-fade-up mt-10 flex w-full flex-col items-center"
          style={{ animationDelay: "180ms" }}
        >
          <WaitlistForm />
        </div>

        {/* Secondary CTAs */}
        <div
          className="gc-fade-up mt-8 flex flex-col items-center gap-4 sm:flex-row"
          style={{ animationDelay: "240ms" }}
        >
          <a
            href={DEMO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-2 rounded-xl border border-white/15 px-5 py-3 text-sm font-medium text-[#f4ece1] transition hover:border-[#d9a441]/50 hover:bg-white/[0.03] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441]"
          >
            See the live demo
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              aria-hidden="true"
              className="transition-transform group-hover:translate-x-0.5"
            >
              <path
                d="M3 11L11 3M11 3H5M11 3V9"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </a>
          <span className="text-sm text-white/30">·</span>
          <a
            href="/sign-in"
            className="rounded-lg px-2 py-1 text-sm font-medium text-white/60 underline-offset-4 transition hover:text-[#f4ece1] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441]"
          >
            Already onboard? Sign in
          </a>
        </div>
      </div>
    </header>
  );
}
