import { render, renderHook, screen } from "@testing-library/react";
import { scaleLinear } from "d3-scale";
import { useRef } from "react";
import { cssVar } from "@/charts/color";
import {
  Axis,
  Band,
  GridLines,
  Legend,
  Line,
  Points,
  ReferenceLine,
  VersionMarkers,
} from "@/charts/primitives";
import { useChartSize } from "@/charts/useChartSize";

const x = scaleLinear().domain([0, 10]).range([0, 200]);
const y = scaleLinear().domain([0, 1]).range([100, 0]);

describe("primitivas de gráficas", () => {
  it("dibujan SVG con los tokens del tema", () => {
    const { container } = render(
      <svg role="img" aria-label="prueba">
        <Axis
          scale={x}
          orientation="bottom"
          length={200}
          format={(v) => `d${v}`}
          label="día (UTC)"
        />
        <Axis
          scale={y}
          orientation="left"
          length={100}
          format={(v) => String(v)}
        />
        <GridLines scale={y} width={200} />
        <Line
          points={[
            { x: 0, y: 0.2 },
            { x: 5, y: null },
            { x: 10, y: 0.8 },
          ]}
          x={x}
          y={y}
          colorVar="--color-bank-bbva"
          dash={[4, 3]}
        />
        <Band
          points={[
            { x: 0, lo: 0.1, hi: 0.3 },
            { x: 10, lo: 0.6, hi: 0.9 },
          ]}
          x={x}
          y={y}
          colorVar="--color-bank-bbva"
        />
        <Points
          points={[{ x: 5, y: 0.5, lo: 0.4, hi: 0.6, label: "mes" }]}
          x={x}
          y={y}
          colorVar="--color-sent-neg"
        />
        <ReferenceLine y={0.5} width={200} scale={y} label="umbral" />
        <VersionMarkers markers={[{ at: 4, label: "v2" }]} x={x} height={100} />
        <Legend
          items={[
            { label: "Banco Azul", colorVar: "--color-bank-bbva", last: 0.8 },
            { label: "sin dato", colorVar: "--color-bank-bbva", last: null },
          ]}
          y={y}
          x={200}
        />
      </svg>,
    );
    expect(screen.getByText("día (UTC)")).toBeInTheDocument();
    expect(screen.getByText("umbral")).toBeInTheDocument();
    expect(screen.getByText("Banco Azul")).toBeInTheDocument();
    expect(screen.queryByText("sin dato")).not.toBeInTheDocument();
    expect(container.querySelector("path")?.getAttribute("stroke")).toBe(
      "var(--color-bank-bbva)",
    );
  });

  it("cssVar lee un token del documento", () => {
    document.documentElement.style.setProperty("--color-prueba", " #123456 ");
    expect(cssVar("--color-prueba")).toBe("#123456");
  });

  it("useChartSize mide el contenedor", () => {
    const el = document.createElement("div");
    Object.defineProperty(el, "clientWidth", { value: 320 });
    Object.defineProperty(el, "clientHeight", { value: 180 });
    const { result } = renderHook(() => useChartSize(useRef(el)));
    expect(result.current).toEqual({ width: 320, height: 180 });
  });
});
