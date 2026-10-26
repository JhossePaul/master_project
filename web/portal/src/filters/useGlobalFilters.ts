import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import { z } from "zod";
import { BANK_IDS, type BankId, isBankId } from "@/config/banks";

export interface GlobalFilters {
  banks: BankId[];
  from: string;
  to: string;
}

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const DEFAULT_DAYS = 90;

export function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function defaultRange(today = new Date()): { from: string; to: string } {
  const from = new Date(today);
  from.setUTCDate(from.getUTCDate() - DEFAULT_DAYS);
  return { from: isoDay(from), to: isoDay(today) };
}

export function parseFilters(
  params: URLSearchParams,
  today = new Date(),
): GlobalFilters {
  const fallback = defaultRange(today);
  const raw = params.get("bancos");
  const banks = raw
    ? [...new Set(raw.split(",").map((b) => b.trim().toUpperCase()))].filter(
        isBankId,
      )
    : [];
  const from = isoDate.safeParse(params.get("desde"));
  const to = isoDate.safeParse(params.get("hasta"));
  let start = from.success ? from.data : fallback.from;
  let end = to.success ? to.data : fallback.to;
  if (start > end) [start, end] = [end, start];
  return {
    banks: banks.length > 0 ? banks : [...BANK_IDS],
    from: start,
    to: end,
  };
}

export function useGlobalFilters(): [
  GlobalFilters,
  (patch: Partial<GlobalFilters>) => void,
] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(params), [params]);

  const update = useCallback(
    (patch: Partial<GlobalFilters>) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          const current = parseFilters(previous);
          const merged = { ...current, ...patch };
          if (
            merged.banks.length === BANK_IDS.length ||
            merged.banks.length === 0
          )
            next.delete("bancos");
          else next.set("bancos", merged.banks.join(","));
          const fallback = defaultRange();
          if (merged.from === fallback.from && merged.to === fallback.to) {
            next.delete("desde");
            next.delete("hasta");
          } else {
            next.set("desde", merged.from);
            next.set("hasta", merged.to);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return [filters, update];
}
