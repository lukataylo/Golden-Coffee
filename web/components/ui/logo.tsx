import * as React from "react";
import { cn } from "@/lib/cn";

/** Golden Coffee bean/steam mark in brand gold. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      className={cn("h-7 w-7", className)}
      fill="none"
    >
      <circle cx="16" cy="16" r="15" stroke="#d9a441" strokeWidth="1.5" />
      <path
        d="M16 7c-2.2 1.6-2.2 3.6 0 5.2s2.2 3.6 0 5.2"
        stroke="#d9a441"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M9 20c1.8 2.6 4.2 4 7 4s5.2-1.4 7-4"
        stroke="#e4bd66"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2.5 text-cream",
        className,
      )}
    >
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">
        Golden <span className="text-gold-400">Coffee</span>
      </span>
    </span>
  );
}
