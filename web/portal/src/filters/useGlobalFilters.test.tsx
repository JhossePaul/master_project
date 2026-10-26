import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { BANK_IDS } from "@/config/banks";
import {
  defaultRange,
  parseFilters,
  useGlobalFilters,
} from "@/filters/useGlobalFilters";

function wrapper(initial: string) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
  );
}

function useBoth() {
  return { filters: useGlobalFilters(), location: useLocation() };
}

describe("parseFilters", () => {
  const today = new Date("2026-10-26T12:00:00Z");

  it("sin parámetros: los cinco bancos y los últimos 90 días", () => {
    const f = parseFilters(new URLSearchParams(), today);
    expect(f.banks).toEqual(BANK_IDS);
    expect(f.to).toBe("2026-10-26");
    expect(f.from).toBe("2026-07-28");
  });

  it("lee bancos y fechas de la URL", () => {
    const f = parseFilters(
      new URLSearchParams(
        "bancos=nubank,BBVA&desde=2026-01-01&hasta=2026-02-01",
      ),
      today,
    );
    expect(f).toEqual({
      banks: ["NUBANK", "BBVA"],
      from: "2026-01-01",
      to: "2026-02-01",
    });
  });

  it("descarta un banco desconocido", () => {
    expect(
      parseFilters(new URLSearchParams("bancos=BBVA,OTRO"), today).banks,
    ).toEqual(["BBVA"]);
    expect(
      parseFilters(new URLSearchParams("bancos=OTRO"), today).banks,
    ).toEqual(BANK_IDS);
  });

  it("ignora fechas inválidas e invierte un rango al revés", () => {
    expect(parseFilters(new URLSearchParams("desde=ayer"), today).from).toBe(
      defaultRange(today).from,
    );
    const f = parseFilters(
      new URLSearchParams("desde=2026-05-01&hasta=2026-03-01"),
      today,
    );
    expect([f.from, f.to]).toEqual(["2026-03-01", "2026-05-01"]);
  });
});

describe("useGlobalFilters", () => {
  it("escribe en la URL y la URL vuelve a leerse", () => {
    const { result } = renderHook(useBoth, {
      wrapper: wrapper("/cockpit?otro=1"),
    });
    act(() =>
      result.current.filters[1]({
        banks: ["BBVA", "NUBANK"],
        from: "2026-01-01",
        to: "2026-02-01",
      }),
    );

    const params = new URLSearchParams(result.current.location.search);
    expect(params.get("bancos")).toBe("BBVA,NUBANK");
    expect(params.get("desde")).toBe("2026-01-01");
    expect(params.get("otro")).toBe("1");
    expect(result.current.filters[0].banks).toEqual(["BBVA", "NUBANK"]);
  });

  it("los valores por defecto no ensucian la URL", () => {
    const { result } = renderHook(useBoth, {
      wrapper: wrapper("/cockpit?bancos=BBVA"),
    });
    act(() =>
      result.current.filters[1]({ banks: [...BANK_IDS], ...defaultRange() }),
    );

    expect(result.current.location.search).toBe("");
  });
});
