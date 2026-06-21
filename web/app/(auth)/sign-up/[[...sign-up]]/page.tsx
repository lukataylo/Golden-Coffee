import type { Metadata } from "next";
import { SignUp } from "@clerk/nextjs";

export const metadata: Metadata = {
  title: "Create your account",
  description: "Start running your café with Caffe Steve.",
};

export default function SignUpPage() {
  return (
    <div className="flex justify-center">
      <SignUp
        signInUrl="/sign-in"
        fallbackRedirectUrl="/onboarding"
        appearance={{ elements: { footer: "hidden" } }}
      />
    </div>
  );
}
