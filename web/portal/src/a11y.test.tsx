import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { renderApp } from "@/test/render";

describe("accesibilidad", () => {
  it("la landing no tiene violaciones de axe", async () => {
    const { container } = renderApp("/");
    await screen.findByRole("heading", { name: "Banco Índigo" });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("el shell con una sección en construcción no tiene violaciones", async () => {
    const { container } = renderApp("/cockpit");
    await screen.findByText("En construcción");
    expect(await axe(container)).toHaveNoViolations();
  });
});
