export type BankId = "BBVA" | "AZTECA" | "SANTANDER" | "NUBANK" | "BANORTE";

export interface BankStyle {
  id: BankId;
  label: string;
  colorVar: string;
  /** Trazo de respaldo para la confusión rojo-verde (stroke-dasharray). */
  dash: number[];
}

export const BANK_IDS: BankId[] = [
  "BBVA",
  "AZTECA",
  "SANTANDER",
  "NUBANK",
  "BANORTE",
];

// label = seudónimo por color (pregunta D-03 del cuestionario de diseño; el color es el representativo del banco).
export const BANKS: Record<BankId, BankStyle> = {
  BBVA: {
    id: "BBVA",
    label: "Banco Azul",
    colorVar: "--color-bank-bbva",
    dash: [],
  },
  AZTECA: {
    id: "AZTECA",
    label: "Banco Verde",
    colorVar: "--color-bank-azteca",
    dash: [8, 4],
  },
  SANTANDER: {
    id: "SANTANDER",
    label: "Banco Rojo",
    colorVar: "--color-bank-santander",
    dash: [2, 3],
  },
  NUBANK: {
    id: "NUBANK",
    label: "Banco Morado",
    colorVar: "--color-bank-nubank",
    dash: [8, 3, 2, 3],
  },
  BANORTE: {
    id: "BANORTE",
    label: "Banco Gris",
    colorVar: "--color-bank-banorte",
    dash: [4, 3],
  },
};

export const ALL_BANKS_STYLE: BankStyle = {
  id: "BBVA",
  label: "Los cinco bancos",
  colorVar: "--color-bank-all",
  dash: [],
};

export function isBankId(value: string): value is BankId {
  return value in BANKS;
}

/** Seudónimo del banco; un id desconocido se devuelve tal cual. */
export function bankLabel(id: string): string {
  return isBankId(id) ? BANKS[id].label : id;
}
