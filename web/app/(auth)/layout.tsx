import Link from "next/link";
import { Wordmark } from "@/components/ui";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="gc-container flex items-center justify-between py-6">
        <Link href="/" aria-label="Caffe Steve home">
          <Wordmark />
        </Link>
        <Link
          href="/"
          className="text-sm text-cream-muted transition-colors hover:text-cream"
        >
          ← Back to site
        </Link>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center px-5 py-10">
        <div className="w-full max-w-md animate-fade-up">
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-cream">
              Your café, but it runs itself
            </h1>
            <p className="mt-2 text-sm text-cream-muted">
              Ambient comfort and ops, from a single camera you already have.
            </p>
          </div>
          {children}
        </div>
      </main>
      <footer className="gc-container py-8 text-center text-xs text-cream-dim">
        Privacy-first · No new hardware · Built for cafés &amp; restaurants
      </footer>
    </div>
  );
}
