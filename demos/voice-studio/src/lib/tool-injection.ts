/** One prompt card's tool registration, as the server broadcasts it with the card
 * (``tools`` on a ``phase_transition`` event). */
export interface ToolInjectionEvent {
  id: string;
  card: number;
  title: string;
  declared: string[];
  added: string[];
  removed: string[];
  /** context_update: swapped mid-session; setup: declared at connect; static: model keeps all tools. */
  via: "context_update" | "setup" | "static";
  /** sent | unchanged | pending (send failed; retried, then declared on reconnect). */
  status: string;
}

let sequence = 0;

/** Read a phase_transition payload's ``tools`` field; null when it has none. */
export function readToolInjection(val: any): ToolInjectionEvent | null {
  const tools = val?.tools;
  if (!tools || !Array.isArray(tools.declared) || !Number.isSafeInteger(tools.card)) return null;
  const list = (x: unknown) => (Array.isArray(x) ? x.filter((n): n is string => typeof n === "string") : []);
  const via = ["context_update", "setup", "static"].includes(tools.via) ? tools.via : "context_update";
  return {
    id: `${tools.card}-${val?.revision ?? ""}-${++sequence}`,
    card: tools.card,
    title: typeof val?.title === "string" ? val.title : `Card ${tools.card}`,
    declared: list(tools.declared),
    added: list(tools.added),
    removed: list(tools.removed),
    via,
    status: typeof tools.status === "string" ? tools.status : "sent",
  };
}

