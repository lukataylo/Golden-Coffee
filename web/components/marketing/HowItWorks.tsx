import type { ReactNode } from "react";

type Feature = {
  title: string;
  body: string;
  icon: ReactNode;
};

const iconProps = {
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "#d9a441",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const FEATURES: Feature[] = [
  {
    title: "Reads the room",
    body: "One existing camera becomes live perception — occupancy, queue length and table waits — updated continuously.",
    icon: (
      <svg {...iconProps}>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    ),
  },
  {
    title: "Tunes the atmosphere",
    body: "An AI agent adjusts music, lighting, scent and temperature to match the moment — calm mornings, buzzing rushes.",
    icon: (
      <svg {...iconProps}>
        <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
        <path d="M1 14h6M9 8h6M17 16h6" />
      </svg>
    ),
  },
  {
    title: "Protects service",
    body: "When queues build or tables wait too long, Caffe Steve flags it and nudges the room back to speed-of-service.",
    icon: (
      <svg {...iconProps}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
  {
    title: "Privacy-first",
    body: "Perception happens on-device. No faces are stored — only the signals needed to run the room well.",
    icon: (
      <svg {...iconProps}>
        <path d="M12 2 4 5v6c0 5 3.5 8 8 11 4.5-3 8-6 8-11V5l-8-3Z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
  },
];

export default function HowItWorks() {
  return (
    <section
      aria-labelledby="how-it-works-heading"
      className="relative mx-auto max-w-6xl px-6 py-20 sm:py-28"
    >
      <div className="mx-auto max-w-2xl text-center">
        <h2
          id="how-it-works-heading"
          className="text-3xl font-semibold tracking-tight sm:text-4xl"
        >
          A copilot for the whole room
        </h2>
        <p className="mt-4 text-pretty text-white/60">
          From a single camera to a calmer, faster, better-feeling venue —
          without giving up your guests&apos; privacy.
        </p>
      </div>

      <ul className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((f) => (
          <li
            key={f.title}
            className="group rounded-2xl border border-white/10 bg-white/[0.025] p-6 transition hover:border-[#d9a441]/40 hover:bg-white/[0.04]"
          >
            <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-[#d9a441]/30 bg-[#d9a441]/10">
              {f.icon}
            </span>
            <h3 className="mt-5 text-lg font-semibold text-[#f4ece1]">
              {f.title}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-white/55">
              {f.body}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
