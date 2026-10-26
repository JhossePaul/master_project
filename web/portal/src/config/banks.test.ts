import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { ALL_BANKS_STYLE, BANK_IDS, BANKS, bankLabel } from "@/config/banks";

const SRC = path.resolve(import.meta.dirname, "..");
const REAL_NAMES = /\b(bbva|azteca|santander|nubank|banorte)\b/i;
const HEX = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/;
// Archivos donde sí viven estos valores.
const EXEMPT = ["styles/tokens.css", "config/banks.ts", "api/schema.d.ts"];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

describe("banks", () => {
  it("hay cinco bancos", () => {
    expect(BANK_IDS).toHaveLength(5);
    expect(Object.keys(BANKS)).toHaveLength(5);
  });

  it("cada colorVar existe en tokens.css", () => {
    const tokens = readFileSync(path.join(SRC, "styles/tokens.css"), "utf8");
    for (const style of [...Object.values(BANKS), ALL_BANKS_STYLE]) {
      expect(tokens).toContain(`${style.colorVar}:`);
    }
  });

  it("ningún label es un nombre real y son distintos", () => {
    const labels = Object.values(BANKS).map((b) => b.label);
    for (const label of labels) expect(label).not.toMatch(REAL_NAMES);
    expect(new Set(labels).size).toBe(5);
  });

  it("bankLabel devuelve el id desconocido tal cual", () => {
    expect(bankLabel("BBVA")).toBe("Banco Índigo");
    expect(bankLabel("OTRO")).toBe("OTRO");
  });

  it("ningún hex ni nombre real de banco fuera de tokens.css, banks.ts y schema.d.ts", () => {
    const offenders: string[] = [];
    for (const file of files(SRC)) {
      const rel = path.relative(SRC, file).split(path.sep).join("/");
      if (
        EXEMPT.includes(rel) ||
        /\.test\.tsx?$/.test(rel) ||
        rel.startsWith("test/")
      )
        continue;
      // El nombre del programa de posgrado es un nombre propio, no un banco.
      const text = readFileSync(file, "utf8").replaceAll(
        "Ciencia de Datos BBVA",
        "",
      );
      if (HEX.test(text) || REAL_NAMES.test(text)) offenders.push(rel);
    }
    expect(offenders).toEqual([]);
  });
});
