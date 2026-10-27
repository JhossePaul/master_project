/** Las familias de la guía de aspectos `v2.1`. */
export type Family =
  | "AC"
  | "TR"
  | "DI"
  | "PR"
  | "AT"
  | "FA"
  | "LE"
  | "CO"
  | "DV"
  | "UX"
  | "OT";

/** Las 11 familias de la guía `v2.1`, con su definición corta. */
export const FAMILY_TEXT: Record<Family, { name: string; help: string }> = {
  AC: {
    name: "Acceso y autenticación",
    help: "Sesión, contraseña, NIP, token, códigos, biometría, registro, bloqueo (en cualquier operación).",
  },
  TR: {
    name: "Transferencias y pagos",
    help: "SPEI, servicios, retiros, cajeros, contactos, comprobantes, restricciones.",
  },
  DI: {
    name: "Dinero y cargos",
    help: "Cargos no reconocidos, comisiones, dinero que falta, fraude.",
  },
  PR: {
    name: "Productos y cuentas",
    help: "Tarjetas, créditos, puntos, saldo, movimientos, trámites.",
  },
  AT: {
    name: "Atención",
    help: "Servicio al cliente, teléfono, chat, sucursal.",
  },
  FA: {
    name: "Falla general",
    help: "No abre, se cierra, no carga, sin conexión.",
  },
  LE: { name: "Lentitud general", help: "Lentitud general de la app." },
  CO: {
    name: "Compatibilidad, instalación y actualización",
    help: "Actualización forzosa o que falla, no se instala, teléfono, permisos, espacio.",
  },
  DV: { name: "Diseño visual", help: "Cómo se ve." },
  UX: {
    name: "Usabilidad",
    help: "Cómo se hace algo, lo que interrumpe el uso (publicidad, notificaciones, idioma) y funciones que quitaron.",
  },
  OT: {
    name: "Sin familia",
    help: "Último recurso, solo si no cabe en ninguna.",
  },
};

/** Orden de decisión de la guía `v2.1`. */
export const FAMILY_GROUPS: { title: string; families: Family[] }[] = [
  {
    title: "1 · ¿Es de una operación o de la autenticación?",
    families: ["AC", "TR", "DI", "PR", "AT"],
  },
  {
    title: "2 · ¿Es de la app en general, su instalación o el teléfono?",
    families: ["FA", "LE", "CO"],
  },
  { title: "3 · ¿Es de diseño?", families: ["DV", "UX"] },
  { title: "4 · Último recurso", families: ["OT"] },
];
