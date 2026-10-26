import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { renderApp } from "@/test/render";

describe("accesibilidad", () => {
  it("la landing no tiene violaciones de axe", async () => {
    const { container } = renderApp("/");
    await screen.findByRole("link", { name: "Banco Azul" });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("el shell con una sección en construcción no tiene violaciones", async () => {
    const { container } = renderApp("/alertas");
    await screen.findByText("En construcción");
    expect(await axe(container)).toHaveNoViolations();
  });
});
