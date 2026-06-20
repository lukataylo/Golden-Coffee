import * as React from "react";
import { cn } from "@/lib/cn";

export interface StepperProps {
  steps: string[];
  /** Zero-based index of the active step. */
  current: number;
  className?: string;
}

/** Accessible horizontal progress indicator for the onboarding wizard. */
export function Stepper({ steps, current, className }: StepperProps) {
  return (
    <nav aria-label="Progress" className={cn("w-full", className)}>
      <ol className="flex items-center gap-2">
        {steps.map((label, i) => {
          const isDone = i < current;
          const isActive = i === current;
          return (
            <li key={label} className="flex flex-1 items-center gap-2">
              <span
                aria-current={isActive ? "step" : undefined}
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                  isDone &&
                    "border-gold-500 bg-gold-500 text-ink-950",
                  isActive &&
                    "border-gold-500 bg-gold-500/15 text-gold-300",
                  !isDone &&
                    !isActive &&
                    "border-cream/15 text-cream-dim",
                )}
              >
                {isDone ? "✓" : i + 1}
              </span>
              <span
                className={cn(
                  "hidden truncate text-xs sm:block",
                  isActive ? "text-cream" : "text-cream-dim",
                )}
              >
                {label}
              </span>
              {i < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-px flex-1 rounded",
                    isDone ? "bg-gold-500/60" : "bg-cream/10",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
