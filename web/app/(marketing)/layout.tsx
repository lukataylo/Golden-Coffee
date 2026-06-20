import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Coffee Steve — Your café, but it runs itself",
  description:
    "An ambient + ops copilot for cafés and restaurants. One camera, privacy-first perception, and an AI agent that tunes the atmosphere and protects speed-of-service.",
  openGraph: {
    title: "Coffee Steve — Your café, but it runs itself",
    description:
      "An ambient + ops copilot for cafés and restaurants. Privacy-first perception meets an AI agent that tunes the room and protects service.",
    type: "website",
  },
};

/**
 * Marketing segment layout. Self-contained: defines its own CSS keyframes via a
 * plain <style> element so it does not depend on the scaffold's globals.css.
 * All animation is CSS-only and disabled under prefers-reduced-motion.
 */
export default function MarketingLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#0e0b08] text-[#f4ece1] antialiased selection:bg-[#d9a441] selection:text-[#0e0b08]">
      {/* Global, scoped-by-class keyframes for the aurora background. */}
      <style
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{
          __html: `
@keyframes gc-aurora-drift {
  0%   { transform: translate3d(-8%, -4%, 0) scale(1.05) rotate(0deg); }
  50%  { transform: translate3d(8%, 6%, 0) scale(1.18) rotate(8deg); }
  100% { transform: translate3d(-8%, -4%, 0) scale(1.05) rotate(0deg); }
}
@keyframes gc-aurora-drift-2 {
  0%   { transform: translate3d(6%, 4%, 0) scale(1.1); }
  50%  { transform: translate3d(-6%, -6%, 0) scale(1.25); }
  100% { transform: translate3d(6%, 4%, 0) scale(1.1); }
}
@keyframes gc-fade-up {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes gc-pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.45; transform: scale(0.8); }
}
.gc-aurora-a { animation: gc-aurora-drift 22s ease-in-out infinite; }
.gc-aurora-b { animation: gc-aurora-drift-2 28s ease-in-out infinite; }
.gc-fade-up { animation: gc-fade-up 0.7s ease-out both; }
.gc-pulse-dot { animation: gc-pulse-dot 2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .gc-aurora-a, .gc-aurora-b, .gc-fade-up, .gc-pulse-dot {
    animation: none !important;
  }
  .gc-fade-up { opacity: 1; transform: none; }
}
`,
        }}
      />
      {children}
    </div>
  );
}
