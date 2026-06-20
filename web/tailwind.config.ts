import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Brand palette — warm-dark with gold accent.
        gold: {
          DEFAULT: "#d9a441",
          50: "#fbf4e3",
          100: "#f4e3bd",
          200: "#ecd092",
          300: "#e4bd66",
          400: "#deae4f",
          500: "#d9a441",
          600: "#b9882f",
          700: "#916923",
          800: "#6a4c19",
          900: "#43300f",
        },
        ink: {
          // Near-black surfaces, slightly warm.
          950: "#0c0a07",
          900: "#141009",
          850: "#1b160d",
          800: "#221b10",
          700: "#2d2415",
          600: "#3a2f1d",
        },
        cream: {
          DEFAULT: "#f6eee4",
          muted: "#cdbfae",
          dim: "#9b8c7b",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(217,164,65,0.18), 0 18px 50px -12px rgba(217,164,65,0.25)",
        card: "0 1px 0 0 rgba(246,238,228,0.04) inset, 0 24px 60px -24px rgba(0,0,0,0.7)",
      },
      backgroundImage: {
        "warm-radial":
          "radial-gradient(120% 90% at 78% -8%, #4d3015 0%, #3a2410 38%, #2a1a0d 72%, #161009 100%)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
