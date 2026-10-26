import {
  formatBytes,
  formatCi,
  formatDate,
  formatDateTime,
  formatInt,
  formatKappa,
  formatMonth,
  formatPct,
  formatStars,
} from "@/lib/format";

describe("formatInt", () => {
  it("usa coma de miles", () => expect(formatInt(2654106)).toBe("2,654,106"));
  it("maneja 0 y negativos", () => {
    expect(formatInt(0)).toBe("0");
    expect(formatInt(-1500)).toBe("-1,500");
  });
  it("devuelve raya con nulos", () => {
    expect(formatInt(null)).toBe("—");
    expect(formatInt(undefined)).toBe("—");
    expect(formatInt(Number.NaN)).toBe("—");
  });
});

describe("formatPct", () => {
  it("un decimal y espacio antes del signo", () =>
    expect(formatPct(0.123)).toBe("12.3 %"));
  it("0 y 1", () => {
    expect(formatPct(0)).toBe("0.0 %");
    expect(formatPct(1)).toBe("100.0 %");
  });
  it("acepta dígitos y negativos", () => {
    expect(formatPct(-0.05, 0)).toBe("-5 %");
    expect(formatPct(0.12345, 2)).toBe("12.35 %");
  });
  it("nulo", () => expect(formatPct(null)).toBe("—"));
});

describe("formatCi", () => {
  it("estimación con intervalo", () =>
    expect(formatCi(0.123, 0.11, 0.136)).toBe("12.3 % [11.0, 13.6]"));
  it("sin intervalo, solo la estimación", () =>
    expect(formatCi(0.123, null, null)).toBe("12.3 %"));
  it("sin estimación", () => expect(formatCi(null, 0.1, 0.2)).toBe("—"));
});

describe("formatStars", () => {
  it("signo explícito", () => {
    expect(formatStars(0.21)).toBe("+0.21 ★");
    expect(formatStars(-0.3)).toBe("−0.30 ★");
  });
  it("cero y nulo", () => {
    expect(formatStars(0)).toBe("0.00 ★");
    expect(formatStars(null)).toBe("—");
  });
});

describe("formatKappa", () => {
  it("tres decimales", () => expect(formatKappa(0.7)).toBe("0.700"));
  it("0, 1 y nulo", () => {
    expect(formatKappa(0)).toBe("0.000");
    expect(formatKappa(1)).toBe("1.000");
    expect(formatKappa(null)).toBe("—");
  });
});

describe("fechas", () => {
  it("día calendario sin correrse de zona", () =>
    expect(formatDate("2026-10-25")).toBe("25 oct 2026"));
  it("mes", () => {
    expect(formatMonth("2026-10")).toBe("oct 2026");
    expect(formatMonth("2026-10-25")).toBe("oct 2026");
  });
  it("fecha y hora en CDMX", () =>
    expect(formatDateTime("2026-10-25T15:30:00Z")).toBe(
      "25 oct 2026, 09:30 CDMX",
    ));
  it("nulos y fechas inválidas", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatMonth(undefined)).toBe("—");
    expect(formatDateTime("no es fecha")).toBe("—");
  });
});

describe("formatBytes", () => {
  it("escala unidades", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });
  it("nulo", () => expect(formatBytes(null)).toBe("—"));
});
