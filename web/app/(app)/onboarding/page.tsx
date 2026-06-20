import type { Metadata } from "next";
import { OnboardingWizard } from "./onboarding-wizard";

export const metadata: Metadata = {
  title: "Get set up",
  description: "Set up your café with Golden Coffee in a few quick steps.",
};

export default function OnboardingPage() {
  return (
    <div className="gc-container py-10 sm:py-14">
      <div className="mx-auto max-w-2xl">
        <OnboardingWizard />
      </div>
    </div>
  );
}
