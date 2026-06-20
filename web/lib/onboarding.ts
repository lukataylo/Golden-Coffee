"use client";

import * as React from "react";

export type VenueType = "cafe" | "restaurant";
export type CameraMode = "stream" | "demo";

export interface OnboardingState {
  venueName: string;
  venueType: VenueType;
  locale: string;
  cameraMode: CameraMode;
  streamUrl: string;
  spaceMapped: boolean;
  completed: boolean;
  completedAt: string | null;
}

export const ONBOARDING_DEFAULTS: OnboardingState = {
  venueName: "",
  venueType: "cafe",
  locale: "en-GB",
  cameraMode: "demo",
  streamUrl: "",
  spaceMapped: false,
  completed: false,
  completedAt: null,
};

const STORAGE_KEY = "gc.onboarding.v1";

function read(): OnboardingState {
  if (typeof window === "undefined") return ONBOARDING_DEFAULTS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return ONBOARDING_DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    return { ...ONBOARDING_DEFAULTS, ...parsed };
  } catch {
    return ONBOARDING_DEFAULTS;
  }
}

function write(state: OnboardingState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

/**
 * Typed client store for the onboarding wizard. Backed by localStorage so a
 * partially-completed wizard survives refreshes. When Clerk Organizations are
 * configured, step 1 also creates a real org; this store remains the source of
 * truth for wizard progress + the "has onboarded" gate.
 */
export function useOnboarding() {
  const [state, setState] = React.useState<OnboardingState>(
    ONBOARDING_DEFAULTS,
  );
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    setState(read());
    setHydrated(true);
  }, []);

  const update = React.useCallback((patch: Partial<OnboardingState>) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      write(next);
      return next;
    });
  }, []);

  const complete = React.useCallback(() => {
    update({ completed: true, completedAt: new Date().toISOString() });
  }, [update]);

  const reset = React.useCallback(() => {
    write(ONBOARDING_DEFAULTS);
    setState(ONBOARDING_DEFAULTS);
  }, []);

  return { state, hydrated, update, complete, reset } as const;
}

/** Read-only completion check for gating the app shell. */
export function readOnboardingCompleted(): boolean {
  return read().completed;
}
