import { useSearchParams } from "react-router";

export const DAY = /^\d{4}-\d{2}-\d{2}$/;
export const MONTH = /^\d{4}-\d{2}$/;
export const FAMILY = /^[A-Za-z]{1,2}$/;
export const BANK = /^[A-Z]+$/;

/** Un parámetro de la URL con su validación; ``null`` lo borra. */
export function useParam(name: string, valid: RegExp) {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = raw && valid.test(raw) ? raw : null;
  const set = (next: string | null) =>
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        if (next) out.set(name, next);
        else out.delete(name);
        return out;
      },
      { replace: true },
    );
  return [value, set] as const;
}

/** Una lista en la URL (``?familia=AC,FA``), solo con los valores permitidos. */
export function useListParam(name: string, allowed: readonly string[]) {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = raw
    ? [...new Set(raw.split(",").filter((t) => allowed.includes(t)))]
    : [];
  const set = (next: string[]) =>
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        if (next.length > 0) out.set(name, next.join(","));
        else out.delete(name);
        return out;
      },
      { replace: true },
    );
  return [value, set] as const;
}
