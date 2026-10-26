import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { KpiCard } from "@/components/KpiCard";
import { Provenance } from "@/components/Provenance";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GLOSSARY } from "@/config/glossary";

describe("Provenance", () => {
  it("solo muestra los campos que aplican", () => {
    render(<Provenance model="m1" dataUntil="2026-10-24" />);
    expect(
      screen.getByText("Modelo m1 · datos al 24 oct 2026"),
    ).toBeInTheDocument();
  });
  it("no pinta nada sin campos", () => {
    const { container } = render(<Provenance />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("StatusPill", () => {
  it("lleva texto, no solo color", () => {
    render(<StatusPill status="reentrenar" />);
    expect(screen.getByText("reentrenar")).toBeInTheDocument();
  });
});

describe("KpiCard", () => {
  it("muestra cifra, intervalo, método y procedencia", () => {
    render(
      <TooltipProvider>
        <KpiCard
          label="Negativas"
          value="12.3 %"
          interval="[11.0, 13.6]"
          method="ppi"
          provenance={{ model: "m1" }}
        />
      </TooltipProvider>,
    );
    expect(screen.getByText("12.3 %")).toBeInTheDocument();
    expect(screen.getByText("[11.0, 13.6]")).toBeInTheDocument();
    expect(screen.getByText("Con revisión humana")).toBeInTheDocument();
    expect(screen.getByText("Modelo m1")).toBeInTheDocument();
  });
});

describe("ChartFrame", () => {
  it("Ver datos abre la tabla con los mismos números", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <TooltipProvider>
        <ChartFrame
          kicker="Sentimiento"
          title="Proporción de negativas"
          provenance={{ model: "m1" }}
          data={{ columns: ["Mes", "NEG"], rows: [["sep 2026", "12.3 %"]] }}
          howToRead="Cada punto es un mes."
        >
          <svg role="img" aria-label="gráfica" />
        </ChartFrame>
      </TooltipProvider>,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ver datos" }));
    expect(screen.getByRole("table")).toHaveTextContent("12.3 %");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("ConfirmWithReason", () => {
  async function open(requireWord?: string) {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmWithReason
        title="Cambiar"
        description="Un cambio grande"
        confirmLabel="Confirmar"
        requireWord={requireWord}
        onConfirm={onConfirm}
        trigger={<Button>Abrir</Button>}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Abrir" }));
    return { user, onConfirm };
  }

  it("exige al menos 10 caracteres de motivo", async () => {
    const { user, onConfirm } = await open();
    const confirm = screen.getByRole("button", { name: "Confirmar" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Motivo/), "corto");
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Motivo/), " ya es largo");
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("corto ya es largo");
  });

  it("con palabra de confirmación, también hay que escribirla", async () => {
    const { user, onConfirm } = await open("CONFIRMAR");
    await user.type(screen.getByLabelText(/Motivo/), "motivo suficiente");
    const confirm = screen.getByRole("button", { name: "Confirmar" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Escribe/), "CONFIRMAR");
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("GlossaryTerm y glosario", () => {
  it("abre la definición", async () => {
    const user = userEvent.setup();
    render(<GlossaryTerm id="ppi" />);
    await user.click(screen.getByRole("button", { name: "PPI" }));
    expect(screen.getByText(GLOSSARY.ppi.short)).toBeInTheDocument();
  });

  it("todas las entradas tienen definición breve y sin códigos del backlog", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.short.length).toBeGreaterThan(20);
      expect(`${entry.term} ${entry.short}`).not.toMatch(
        /\b(M\d+|P\d+-\d+|D\d+|F-\d+)\b/,
      );
    }
    expect(Object.keys(GLOSSARY).length).toBeGreaterThanOrEqual(27);
  });
});

describe("Callout", () => {
  it("el aviso informativo es una nota", () => {
    render(<Callout>Describe lo que dicen las reseñas.</Callout>);
    expect(screen.getByRole("note")).toBeInTheDocument();
  });
});
