import Wordmark from "./Wordmark";

const DEMO_URL = "https://golden-coffee-production.up.railway.app";

export default function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-white/10">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 px-6 py-10 sm:flex-row">
        <Wordmark />
        <p className="text-center text-sm text-white/45 sm:text-left">
          Privacy-first by design — no faces stored, ever.
        </p>
        <div className="flex items-center gap-5 text-sm">
          <a
            href={DEMO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-white/55 transition hover:text-[#d9a441] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441]"
          >
            Live demo
          </a>
          <a
            href="/sign-in"
            className="text-white/55 transition hover:text-[#d9a441] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d9a441]"
          >
            Sign in
          </a>
        </div>
      </div>
      <div className="mx-auto max-w-6xl px-6 pb-8">
        <p className="text-xs text-white/30">
          © {year} Caffe Steve. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
