"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useOrganizationList } from "@clerk/nextjs";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Label,
  RadioCards,
  Select,
  Stepper,
} from "@/components/ui";
import { useOnboarding } from "@/lib/onboarding";
import { env } from "@/lib/env";

const STEPS = ["Your café", "Connect camera", "Map space", "Done"] as const;

const LOCALES = [
  { value: "en-GB", label: "English (UK)" },
  { value: "en-US", label: "English (US)" },
  { value: "fr-FR", label: "Français" },
  { value: "es-ES", label: "Español" },
  { value: "it-IT", label: "Italiano" },
  { value: "de-DE", label: "Deutsch" },
] as const;

export function OnboardingWizard() {
  const router = useRouter();
  const { state, hydrated, update, complete } = useOnboarding();
  const { createOrganization, isLoaded: orgLoaded } = useOrganizationList();

  const [step, setStep] = React.useState(0);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (!hydrated) {
    return (
      <Card aria-busy="true">
        <CardContent className="p-10">
          <div className="h-2 w-1/3 animate-pulse rounded bg-cream/10" />
          <div className="mt-4 h-24 animate-pulse rounded bg-cream/5" />
        </CardContent>
      </Card>
    );
  }

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  async function handleVenueSubmit() {
    setError(null);
    if (!state.venueName.trim()) {
      setError("Please give your café a name.");
      return;
    }
    setSubmitting(true);
    // Best-effort: create a Clerk Organization for multi-venue tenancy. If the
    // Organizations feature isn't enabled, we still proceed with the local store.
    try {
      if (orgLoaded && createOrganization) {
        await createOrganization({ name: state.venueName.trim() });
      }
    } catch {
      // Non-fatal — onboarding continues with the local store as source of truth.
    } finally {
      setSubmitting(false);
      next();
    }
  }

  function finish() {
    complete();
    router.push("/dashboard");
  }

  return (
    <div className="animate-fade-up space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-cream">
          Let&apos;s set up your café
        </h1>
        <p className="mt-1.5 text-sm text-cream-muted">
          A few quick steps and Golden Coffee starts running the room.
        </p>
      </div>

      <Stepper steps={[...STEPS]} current={step} />

      {/* Step 1 — Create café / organization */}
      {step === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Create your café</CardTitle>
            <CardDescription>
              This becomes your venue workspace. You can add more venues later.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <Field>
              <Label htmlFor="venueName">Café name</Label>
              <Input
                id="venueName"
                placeholder="e.g. The Golden Bean"
                value={state.venueName}
                onChange={(e) => update({ venueName: e.target.value })}
                autoFocus
              />
            </Field>

            <Field>
              <Label>Venue type</Label>
              <RadioCards
                name="venueType"
                value={state.venueType}
                onChange={(venueType) => update({ venueType })}
                options={[
                  {
                    value: "cafe",
                    label: "Café",
                    description: "Counter service, fast turnover",
                    icon: "☕",
                  },
                  {
                    value: "restaurant",
                    label: "Restaurant",
                    description: "Table service, longer dwell",
                    icon: "🍽️",
                  },
                ]}
              />
            </Field>

            <Field>
              <Label htmlFor="locale">Locale</Label>
              <Select
                id="locale"
                value={state.locale}
                onChange={(e) => update({ locale: e.target.value })}
              >
                {LOCALES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </Field>

            {error && (
              <p role="alert" className="text-sm text-[#e87a5b]">
                {error}
              </p>
            )}

            <div className="flex justify-end pt-1">
              <Button onClick={handleVenueSubmit} disabled={submitting}>
                {submitting ? "Creating…" : "Continue"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2 — Connect your camera */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Connect your camera</CardTitle>
            <CardDescription>
              Golden Coffee runs on one camera you already have — no new
              hardware. We process the feed privately; faces are never stored.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <RadioCards
              name="cameraMode"
              value={state.cameraMode}
              onChange={(cameraMode) => update({ cameraMode })}
              options={[
                {
                  value: "stream",
                  label: "My camera stream",
                  description: "Paste an RTSP or HTTP stream URL",
                  icon: "📹",
                },
                {
                  value: "demo",
                  label: "Use demo feed",
                  description: "Explore with a sample café first",
                  icon: "✨",
                },
              ]}
            />

            {state.cameraMode === "stream" && (
              <Field>
                <Label htmlFor="streamUrl">Stream URL</Label>
                <Input
                  id="streamUrl"
                  inputMode="url"
                  placeholder="rtsp://192.168.1.10:554/stream"
                  value={state.streamUrl}
                  onChange={(e) => update({ streamUrl: e.target.value })}
                />
                <p className="text-xs text-cream-dim">
                  Most IP cameras expose an RTSP URL in their settings. You can
                  change this anytime.
                </p>
              </Field>
            )}

            <div className="flex items-center justify-between pt-1">
              <Button variant="ghost" onClick={back}>
                ← Back
              </Button>
              <Button onClick={next}>Continue</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3 — Map your space */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Map your space</CardTitle>
            <CardDescription>
              Open the floorplan scanner to walk your room and place tables. It
              builds the live 3D twin your dashboard uses.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="rounded-xl border border-cream/10 bg-ink-850 p-5">
              <p className="text-sm text-cream-muted">
                The scanner opens in a new tab (works great on your phone). When
                you&apos;re done, come back here and continue.
              </p>
              <div className="mt-4">
                <a
                  href={env.scanUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  onClick={() => update({ spaceMapped: true })}
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gold-500 px-5 text-sm font-semibold text-ink-950 shadow-glow transition-colors hover:bg-gold-400"
                >
                  Open floorplan scanner ↗
                </a>
              </div>
            </div>

            <label className="flex items-center gap-3 text-sm text-cream-muted">
              <input
                type="checkbox"
                checked={state.spaceMapped}
                onChange={(e) => update({ spaceMapped: e.target.checked })}
                className="h-4 w-4 rounded border-cream/20 bg-ink-850 accent-gold-500"
              />
              I&apos;ve mapped my space (or I&apos;ll do it later)
            </label>

            <div className="flex items-center justify-between pt-1">
              <Button variant="ghost" onClick={back}>
                ← Back
              </Button>
              <Button onClick={next}>Continue</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4 — Done */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>You&apos;re all set</CardTitle>
            <CardDescription>
              {state.venueName
                ? `${state.venueName} is ready.`
                : "Your café is ready."}{" "}
              Open the live dashboard to watch the room come to life.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <dl className="grid gap-3 rounded-xl border border-cream/10 bg-ink-850 p-5 text-sm sm:grid-cols-2">
              <Summary label="Café">{state.venueName || "—"}</Summary>
              <Summary label="Type">
                {state.venueType === "cafe" ? "Café" : "Restaurant"}
              </Summary>
              <Summary label="Locale">{state.locale}</Summary>
              <Summary label="Camera">
                {state.cameraMode === "demo" ? "Demo feed" : "My stream"}
              </Summary>
            </dl>

            <div className="flex items-center justify-between pt-1">
              <Button variant="ghost" onClick={back}>
                ← Back
              </Button>
              <Button onClick={finish}>Go to dashboard →</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Summary({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-cream-dim">
        {label}
      </dt>
      <dd className="mt-0.5 font-medium text-cream">{children}</dd>
    </div>
  );
}
