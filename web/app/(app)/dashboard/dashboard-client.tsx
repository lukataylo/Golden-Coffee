"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import {
  ButtonLink,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { useOnboarding } from "@/lib/onboarding";
import { env } from "@/lib/env";

export function DashboardClient() {
  const router = useRouter();
  const { state, hydrated } = useOnboarding();
  const { user, isLoaded: userLoaded } = useUser();

  // Gate: send un-onboarded users to the wizard once the local store hydrates.
  React.useEffect(() => {
    if (hydrated && !state.completed) {
      router.replace("/onboarding");
    }
  }, [hydrated, state.completed, router]);

  if (!hydrated || !state.completed) {
    return (
      <div
        className="gc-container flex min-h-[60vh] items-center justify-center"
        aria-busy="true"
      >
        <div className="text-sm text-cream-dim">Loading your café…</div>
      </div>
    );
  }

  const greetingName = userLoaded ? user?.firstName : null;

  return (
    <div className="gc-container space-y-8 py-8 sm:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-cream-dim">
            {greetingName ? `Welcome back, ${greetingName}` : "Welcome back"}
          </p>
          <h1 className="mt-0.5 text-2xl font-semibold tracking-tight text-cream">
            {state.venueName || "Your café"}
          </h1>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-cream/10 bg-ink-850 px-3 py-1.5 font-mono text-xs text-cream-muted">
          <span className="h-2 w-2 animate-pulse rounded-full bg-gold-400" />
          {state.cameraMode === "demo" ? "Demo feed" : "Live feed"}
        </span>
      </header>

      {/* Primary actions */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2 overflow-hidden">
          <CardHeader>
            <CardTitle>Live dashboard</CardTitle>
            <CardDescription>
              Real-time comfort, occupancy and ops — streaming from your venue.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="relative aspect-video w-full overflow-hidden rounded-xl border border-cream/10 bg-ink-950">
              <iframe
                src={env.dashboardUrl}
                title="Coffee Steve live dashboard"
                className="absolute inset-0 h-full w-full"
                loading="lazy"
                referrerPolicy="no-referrer"
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              />
            </div>
            <ButtonLink href={env.dashboardUrl} className="w-full sm:w-auto">
              Open live dashboard ↗
            </ButtonLink>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Scan floorplan</CardTitle>
              <CardDescription>
                Re-map your room or add tables with the mobile scanner.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ButtonLink
                href={env.scanUrl}
                variant="outline"
                className="w-full"
              >
                Open scanner ↗
              </ButtonLink>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Setup</CardTitle>
              <CardDescription>
                Camera and space configuration.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Venue type">
                {state.venueType === "cafe" ? "Café" : "Restaurant"}
              </Row>
              <Row label="Locale">{state.locale}</Row>
              <Row label="Camera">
                {state.cameraMode === "demo" ? "Demo feed" : "My stream"}
              </Row>
              <Row label="Space mapped">
                {state.spaceMapped ? "Yes" : "Not yet"}
              </Row>
              <div className="pt-2">
                <ButtonLink
                  href="/onboarding"
                  variant="ghost"
                  size="sm"
                  className="px-0"
                >
                  Edit setup →
                </ButtonLink>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-cream-dim">{label}</span>
      <span className="font-medium text-cream">{children}</span>
    </div>
  );
}
