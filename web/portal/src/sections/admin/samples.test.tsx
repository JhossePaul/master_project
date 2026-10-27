import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

describe("pestaña Muestras", () => {
  it("lista los lotes y crea una muestra con su motivo", async () => {
    const created: Record<string, unknown>[] = [];
    server.use(
      http.get("*/api/v1/admin/samples", () =>
        HttpResponse.json({
          batches: [
            {
              batch: "ab12cd34",
              task: "aspects",
              created_at: "2026-10-20T10:00:00Z",
              size: 50,
              reviewed: 12,
            },
          ],
        }),
      ),
      http.post("*/api/v1/admin/samples/aspects", async ({ request }) => {
        created.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          {
            batch: "ff00ee11",
            created: 20,
            per_bank: { BBVA: 10, NUBANK: 10 },
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    const { container } = renderApp("/admin?tab=muestras");

    expect(await screen.findByText("ab12cd34")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Reseñas"));
    await user.type(screen.getByLabelText("Reseñas"), "20");
    await user.click(screen.getByRole("button", { name: "Crear muestra…" }));
    await user.type(
      await screen.findByLabelText(/Motivo/),
      "Revalidar las familias",
    );
    await user.click(screen.getByRole("button", { name: "Crear muestra" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toEqual({
      size: 20,
      months: 3,
      reason: "Revalidar las familias",
    });
    expect(await axe(container)).toHaveNoViolations();
  });
});
