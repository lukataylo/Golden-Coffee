import * as React from "react";
import { cn } from "@/lib/cn";

export function Field({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-1.5", className)} {...props} />;
}

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("block text-sm font-medium text-cream-muted", className)}
      {...props}
    />
  );
}

const fieldBase =
  "w-full rounded-xl border border-cream/10 bg-ink-850 px-3.5 py-2.5 text-sm text-cream placeholder:text-cream-dim transition-colors focus:border-gold-500/60 focus:outline-none focus:ring-2 focus:ring-gold-500/30 disabled:opacity-50";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(fieldBase, className)} {...props} />
));
Input.displayName = "Input";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn(fieldBase, "appearance-none", className)} {...props} />
));
Select.displayName = "Select";

export interface RadioCardOption<T extends string> {
  value: T;
  label: string;
  description?: string;
  icon?: React.ReactNode;
}

export interface RadioCardsProps<T extends string> {
  name: string;
  value: T;
  options: ReadonlyArray<RadioCardOption<T>>;
  onChange: (value: T) => void;
  className?: string;
}

/** Segmented set of large selectable cards (used for café vs. restaurant). */
export function RadioCards<T extends string>({
  name,
  value,
  options,
  onChange,
  className,
}: RadioCardsProps<T>) {
  return (
    <div
      role="radiogroup"
      className={cn("grid gap-3 sm:grid-cols-2", className)}
    >
      {options.map((opt) => {
        const selected = opt.value === value;
        return (
          <label
            key={opt.value}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors",
              selected
                ? "border-gold-500/70 bg-gold-500/10"
                : "border-cream/10 bg-ink-850 hover:border-cream/25",
            )}
          >
            <input
              type="radio"
              name={name}
              value={opt.value}
              checked={selected}
              onChange={() => onChange(opt.value)}
              className="sr-only"
            />
            {opt.icon && (
              <span aria-hidden="true" className="mt-0.5 text-xl">
                {opt.icon}
              </span>
            )}
            <span className="space-y-0.5">
              <span className="block text-sm font-semibold text-cream">
                {opt.label}
              </span>
              {opt.description && (
                <span className="block text-xs text-cream-dim">
                  {opt.description}
                </span>
              )}
            </span>
          </label>
        );
      })}
    </div>
  );
}
