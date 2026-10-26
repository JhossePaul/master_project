import { HttpResponse, http } from "msw";
import { ApiError, buildClient } from "@/api/client";
import { server } from "@/test/server";

describe("cliente de la API", () => {
  it("convierte un error en ApiError con su request_id", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(
          { error: { code: "forbidden", message: "No", request_id: "r-1" } },
          { status: 403 },
        ),
      ),
    );
    const error = await buildClient()
      .GET("/api/v1/me")
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      code: "forbidden",
      message: "No",
      requestId: "r-1",
    });
  });

  it("una respuesta que no es JSON también da ApiError", async () => {
    server.use(
      http.get(
        "*/api/v1/me",
        () =>
          new HttpResponse("<html>login</html>", {
            status: 502,
            headers: { "x-request-id": "r-2" },
          }),
      ),
    );
    const error = await buildClient()
      .GET("/api/v1/me")
      .catch((e: unknown) => e);

    expect(error).toMatchObject({
      status: 502,
      code: "unknown",
      requestId: "r-2",
    });
  });
});
