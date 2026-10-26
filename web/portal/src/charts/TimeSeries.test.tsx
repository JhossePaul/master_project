import { render } from "@testing-library/react";
import { TimeSeries } from "@/charts/TimeSeries";

const created = vi.hoisted(() => ({
  args: [] as unknown[][],
  destroyed: 0,
  annotations: [] as unknown[],
}));

vi.mock("dygraphs", () => ({
  default: class {
    constructor(...args: unknown[]) {
      created.args.push(args);
    }
    ready(fn: () => void) {
      fn();
    }
    setAnnotations(a: unknown[]) {
      created.annotations = a;
    }
    destroy() {
      created.destroyed += 1;
    }
  },
}));

describe("TimeSeries", () => {
  it("crea la gráfica con las series y la destruye al desmontar", () => {
    const { unmount, getByRole } = render(
      <TimeSeries
        series={[
          {
            id: "a",
            label: "Banco Índigo",
            colorVar: "--color-bank-bbva",
            dash: [4, 3],
            points: [
              [new Date("2026-10-01"), 0.2],
              [new Date("2026-10-02"), null],
            ],
          },
        ]}
        markers={[{ at: new Date("2026-10-01"), label: "v2" }]}
        valueFormatter={(v) => `${v}`}
        height={200}
      />,
    );
    expect(getByRole("img")).toHaveAccessibleName(
      "Serie de tiempo: Banco Índigo",
    );
    expect(created.args).toHaveLength(1);
    const options = created.args[0]?.[2] as { labels: string[] };
    expect(options.labels).toEqual(["día (UTC)", "Banco Índigo"]);
    expect(created.annotations).toHaveLength(1);

    unmount();
    expect(created.destroyed).toBe(1);
  });

  it("sin series no crea nada", () => {
    created.args.length = 0;
    render(<TimeSeries series={[]} valueFormatter={String} height={100} />);
    expect(created.args).toHaveLength(0);
  });
});
