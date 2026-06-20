import type { Metadata } from "next";
import { SignIn } from "@clerk/nextjs";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to your Coffee Steve account.",
};

export default function SignInPage() {
  return (
    <div className="flex justify-center">
      <SignIn
        signUpUrl="/sign-up"
        fallbackRedirectUrl="/dashboard"
        appearance={{ elements: { footer: "hidden" } }}
      />
    </div>
  );
}
