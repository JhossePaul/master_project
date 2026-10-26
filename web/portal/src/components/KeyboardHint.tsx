import type { ReactNode } from "react";

export interface Shortcut {
  keys: string;
  action: ReactNode;
}

/** Atajos de teclado visibles junto a la pantalla que los usa. */
export function KeyboardHint({ shortcuts }: { shortcuts: Shortcut[] }) {
  return (
    <dl
      aria-label="Atajos de teclado"
      className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-muted"
    >
      {shortcuts.map(({ keys, action }) => (
        <div key={keys} className="flex items-center gap-1.5">
          <dt>
            <kbd className="rounded-sm border border-border-strong bg-neutral-100 px-1.5 py-0.5 font-mono text-text">
              {keys}
            </kbd>
          </dt>
          <dd>{action}</dd>
        </div>
      ))}
    </dl>
  );
}
