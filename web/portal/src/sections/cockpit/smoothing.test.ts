import { type DailyLike, dayShift, rolling } from "./smoothing";

function row(
  dia: string,
  predichas: number,
  neg: number,
  gap: number | null = null,
): DailyLike {
  return { dia, predichas, neg, neg_4_5: Math.floor(neg / 2), gap_crudo: gap };
}

describe("rolling", () => {
  const rows = [
    row("2026-10-01", 100, 50),
    row("2026-10-02", 10, 0),
    row("2026-10-03", 10, 10),
  ];

  it("sin suavizar es el dato de cada día", () => {
    expect(rolling(rows, 1, "neg").map((p) => p.value)).toEqual([0.5, 0, 1]);
  });

  it("pesa cada día por sus reseñas (no promedia las proporciones)", () => {
    const [, , third] = rolling(rows, 3, "neg");

    // 60 / 120 = 0.5; el promedio simple de 0.5, 0 y 1 daría 0.5 por azar,
    // así que se comprueba también el segundo día: 50 / 110.
    expect(third?.value).toBeCloseTo(0.5);
    expect(rolling(rows, 3, "neg")[1]?.value).toBeCloseTo(50 / 110);
  });

  it("la ventana termina en el día y deja fuera lo anterior", () => {
    const out = rolling(rows, 2, "neg");

    expect(out[2]?.value).toBeCloseTo(10 / 20);
    expect(out[1]?.value).toBeCloseTo(50 / 110);
  });

  it("el gap pesa por reseñas y salta los días sin gap", () => {
    const data = [
      row("2026-10-01", 10, 0, -1),
      row("2026-10-02", 30, 0, -3),
      row("2026-10-03", 5, 0, null),
    ];

    expect(rolling(data, 3, "gap")[2]?.value).toBeCloseTo(-100 / 40);
    expect(
      rolling([row("2026-10-03", 5, 0, null)], 7, "gap")[0]?.value,
    ).toBeNull();
  });

  it("las quejas con 4-5 estrellas usan sus propias cuentas", () => {
    expect(rolling(rows, 1, "neg45")[0]?.value).toBeCloseTo(25 / 100);
  });

  it("dayShift cruza el mes", () => {
    expect(dayShift("2026-10-01", -1)).toBe("2026-09-30");
    expect(dayShift("2026-10-26", -27)).toBe("2026-09-29");
  });
});
