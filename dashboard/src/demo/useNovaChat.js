import { useCallback, useState } from "react";
import { cancelTransfer, chatWithNova, confirmTransfer, describeError } from "./demoApi";

const WELCOME = {
  id: "welcome", role: "agent",
  text: "Hello Alex, I'm Nova AI. I can check your balance, list recent transactions, summarize your portfolio, and prepare or cancel transfers. Money only moves after you confirm.",
};

let counter = 0;
const nextId = () => `m${++counter}`;

// Chat state for Nova AI. The server decides what each tool call does; this only shows it.
export function useNovaChat({ onPayload, track }) {
  const [messages, setMessages] = useState([WELCOME]);
  const [busy, setBusy] = useState(false);
  const add = (message) => setMessages((current) => [...current, { id: nextId(), ...message }]);

  const send = useCallback(async (text, content) => {
    const trimmed = (text || "").trim();
    if (!trimmed || busy) return;
    add({ role: "user", text: trimmed });
    setBusy(true);
    void track?.({ action: "form.submit", resource: { id: "nova-chat", type: "form", sensitivity: "low" } });
    try {
      const body = await chatWithNova(trimmed, content);
      onPayload?.(body);
      add({ role: "agent", text: body.reply, steps: body.steps || [] });
    } catch (err) {
      add({ role: "agent", error: true, text: describeError(err, "I couldn't complete that just now.") });
    } finally {
      setBusy(false);
    }
  }, [busy, onPayload, track]);

  const settle = useCallback(async (kind, txId) => {
    try {
      const body = await (kind === "confirm" ? confirmTransfer(txId) : cancelTransfer(txId));
      onPayload?.(body);
      add({ role: "agent", text: body.status === "error" ? body.message
        : kind === "confirm" ? `Done. ${txId} is settled.` : `Cancelled ${txId}; the funds are back in your balance.` });
    } catch (err) {
      add({ role: "agent", error: true, text: describeError(err, "That didn't go through.") });
    }
  }, [onPayload]);

  return { messages, busy, send, confirm: (id) => settle("confirm", id), cancel: (id) => settle("cancel", id) };
}
