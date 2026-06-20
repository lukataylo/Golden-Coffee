/**
 * Inline SVG wordmark/logo mark for Golden Coffee — a stylized coffee bean
 * inside a gold ring. Self-contained, no image assets.
 */
export default function Wordmark({
  className = "",
}: {
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg
        width="32"
        height="32"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <circle
          cx="16"
          cy="16"
          r="14"
          stroke="#d9a441"
          strokeWidth="1.75"
        />
        <ellipse
          cx="16"
          cy="16"
          rx="7"
          ry="10"
          fill="#d9a441"
          fillOpacity="0.18"
        />
        <path
          d="M16 6c-3 3.5-3 12.5 0 20M16 6c3 3.5 3 12.5 0 20"
          stroke="#d9a441"
          strokeWidth="1.75"
          strokeLinecap="round"
        />
      </svg>
      <span className="text-lg font-semibold tracking-tight text-[#f4ece1]">
        Golden{" "}
        <span className="text-[#d9a441]">Coffee</span>
      </span>
    </span>
  );
}
