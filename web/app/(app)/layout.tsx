import Link from "next/link";
import { UserButton, OrganizationSwitcher } from "@clerk/nextjs";
import { Wordmark } from "@/components/ui";
import { env } from "@/lib/env";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-cream/10 bg-ink-950/80 backdrop-blur">
        <div className="gc-container flex h-16 items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Link href="/dashboard" aria-label="Coffee Steve dashboard">
              <Wordmark />
            </Link>
            <span className="hidden h-5 w-px bg-cream/10 sm:block" />
            <OrganizationSwitcher
              hidePersonal
              afterCreateOrganizationUrl="/dashboard"
              afterSelectOrganizationUrl="/dashboard"
              appearance={{
                elements: { rootBox: "hidden sm:flex" },
              }}
            />
          </div>
          <div className="flex items-center gap-3">
            <a
              href={env.dashboardUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="hidden text-sm text-cream-muted transition-colors hover:text-cream md:block"
            >
              Live dashboard ↗
            </a>
            <UserButton
              afterSignOutUrl="/"
              appearance={{
                elements: { avatarBox: "h-9 w-9" },
              }}
            />
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
