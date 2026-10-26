/** Franja diagonal de la marca (guía visual, sección 6). Decorativa. */
export function Tahali({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 240 120"
      preserveAspectRatio="none"
      className={className}
    >
      <polygon
        points="150,0 190,0 90,120 50,120"
        fill="var(--color-gold-400)"
      />
      <polygon
        points="200,0 214,0 114,120 100,120"
        fill="var(--color-gold-300)"
        opacity="0.7"
      />
    </svg>
  );
}
