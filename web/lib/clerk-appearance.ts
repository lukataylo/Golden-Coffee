import type { Appearance } from "@clerk/types";

/**
 * Shared on-brand appearance for all mounted Clerk components
 * (<SignIn/>, <SignUp/>, <UserButton/>, <OrganizationSwitcher/>).
 */
export const clerkAppearance: Appearance = {
  variables: {
    colorPrimary: "#d9a441",
    colorBackground: "#141009",
    colorText: "#f6eee4",
    colorTextSecondary: "#cdbfae",
    colorInputBackground: "#1b160d",
    colorInputText: "#f6eee4",
    colorDanger: "#e87a5b",
    borderRadius: "0.75rem",
    fontFamily: 'var(--font-sans), "Hanken Grotesk", system-ui, sans-serif',
  },
  elements: {
    card: "bg-ink-900/80 border border-cream/10 shadow-card backdrop-blur",
    headerTitle: "text-cream",
    headerSubtitle: "text-cream-muted",
    socialButtonsBlockButton:
      "border border-cream/10 bg-ink-850 text-cream hover:bg-ink-800",
    formButtonPrimary:
      "bg-gold-500 hover:bg-gold-400 text-ink-950 font-semibold normal-case",
    footerActionLink: "text-gold-400 hover:text-gold-300",
    formFieldInput: "bg-ink-850 border-cream/10 text-cream",
    formFieldLabel: "text-cream-muted",
    dividerLine: "bg-cream/10",
    dividerText: "text-cream-dim",
    identityPreviewText: "text-cream",
    userButtonPopoverCard: "bg-ink-900 border border-cream/10",
    organizationSwitcherTrigger:
      "text-cream border border-cream/10 hover:bg-ink-800 rounded-lg",
  },
};
