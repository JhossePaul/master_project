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

// label = seudónimo por color (pregunta D-03 del cuestionario de diseño).
export const BANKS: Record<BankId, BankStyle> = {
  BBVA: {
    id: "BBVA",
    label: "Banco Índigo",
    colorVar: "--color-bank-bbva",
    dash: [],
  },
  AZTECA: {
    id: "AZTECA",
    label: "Banco Jade",
    colorVar: "--color-bank-azteca",
    dash: [8, 4],
  },
  SANTANDER: {
    id: "SANTANDER",
    label: "Banco Carmín",
    colorVar: "--color-bank-santander",
    dash: [2, 3],
  },
  NUBANK: {
    id: "NUBANK",
    label: "Banco Violeta",
    colorVar: "--color-bank-nubank",
    dash: [8, 3, 2, 3],
  },
  BANORTE: {
    id: "BANORTE",
    label: "Banco Ónix",
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
