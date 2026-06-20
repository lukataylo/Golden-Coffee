/**
 * Warm "aurora" backdrop — pure CSS, no JS, no deps.
 * Two blurred radial blobs drift slowly behind the hero. Motion is killed via
 * the `gc-aurora-*` classes when prefers-reduced-motion is set (see layout).
 */
export default function AuroraBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    >
      {/* Base warm vignette */}
      <div className="absolute inset-0 bg-[#0e0b08]" />
      {/* Gold blob */}
      <div className="gc-aurora-a absolute left-1/2 top-[-10%] h-[55vmax] w-[55vmax] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(217,164,65,0.35),rgba(217,164,65,0)_70%)] blur-3xl" />
      {/* Amber/ember blob */}
      <div className="gc-aurora-b absolute right-[-10%] top-[20%] h-[45vmax] w-[45vmax] rounded-full bg-[radial-gradient(closest-side,rgba(196,108,46,0.28),rgba(196,108,46,0)_70%)] blur-3xl" />
      {/* Deep cocoa blob bottom-left for balance */}
      <div className="gc-aurora-a absolute bottom-[-15%] left-[-5%] h-[40vmax] w-[40vmax] rounded-full bg-[radial-gradient(closest-side,rgba(120,80,40,0.22),rgba(120,80,40,0)_70%)] blur-3xl" />
      {/* Subtle grain/scrim so text stays readable */}
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(14,11,8,0.1),rgba(14,11,8,0.85))]" />
    </div>
  );
}
