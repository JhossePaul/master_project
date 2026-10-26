import { hasRole } from "@/auth/roles";

describe("hasRole", () => {
  it("todo rol incluye al lector", () => {
    expect(hasRole({ roles: ["revisor"] }, "lector")).toBe(true);
    expect(hasRole({ roles: [] }, "lector")).toBe(false);
  });
  it("el administrador incluye al analista, pero no al revisor", () => {
    expect(hasRole({ roles: ["administrador"] }, "analista")).toBe(true);
    expect(hasRole({ roles: ["administrador"] }, "revisor")).toBe(false);
  });
  it("sin usuario no hay rol", () =>
    expect(hasRole(undefined, "lector")).toBe(false));
});
