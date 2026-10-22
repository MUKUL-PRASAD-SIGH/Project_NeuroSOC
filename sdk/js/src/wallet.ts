// Wallet awareness without touching the wallet: the SDK listens to the events injected providers
// already emit and, for EVM wallets, asks which accounts the site is *already* allowed to see
// (eth_accounts, which never opens a prompt). It never wraps or patches a provider and never
// calls a signing or connection-request method.

export type Chain = "solana" | "evm";
type Connect = (address: string, chain: Chain) => void;
type Disconnect = (chain: Chain) => void;

interface Provider {
  on?: (event: string, handler: (...args: unknown[]) => void) => void;
  removeListener?: (event: string, handler: (...args: unknown[]) => void) => void;
  off?: (event: string, handler: (...args: unknown[]) => void) => void;
  request?: (args: { method: string }) => Promise<unknown>;
  publicKey?: { toString(): string } | null;
  isConnected?: boolean | (() => boolean);
  providers?: Provider[];
}

interface Win {
  solana?: Provider;
  phantom?: { solana?: Provider };
  ethereum?: Provider;
}

const text = (value: unknown): string => {
  if (value && typeof (value as { toString?: unknown }).toString === "function") return String(value);
  return "";
};

export function watchWallets(onConnect: Connect, onDisconnect: Disconnect): () => void {
  const win = window as unknown as Win;
  const seen = new WeakSet<object>();
  const undo: Array<() => void> = [];
  let stopped = false;

  const listen = (provider: Provider, event: string, handler: (...args: unknown[]) => void) => {
    try {
      provider.on?.(event, handler);
      undo.push(() => {
        try { (provider.removeListener ?? provider.off)?.call(provider, event, handler); } catch { /* provider gone */ }
      });
    } catch { /* a provider that rejects listeners is ignored */ }
  };

  const attachSolana = (provider: Provider) => {
    const connected = (key?: unknown) => {
      const address = text(key) || text(provider.publicKey);
      if (address) onConnect(address, "solana");
    };
    listen(provider, "connect", connected);
    listen(provider, "accountChanged", (key) => (key ? connected(key) : onDisconnect("solana")));
    listen(provider, "disconnect", () => onDisconnect("solana"));
    if (provider.publicKey) connected(provider.publicKey);
  };

  const attachEvm = (provider: Provider) => {
    const accounts = (list: unknown) => {
      const first = Array.isArray(list) ? text(list[0]) : "";
      if (first) onConnect(first.toLowerCase(), "evm");
      else onDisconnect("evm");
    };
    listen(provider, "accountsChanged", accounts);
    listen(provider, "disconnect", () => onDisconnect("evm"));
    // Accounts the site may already see (it was connected earlier). Never prompts.
    void provider.request?.({ method: "eth_accounts" }).then((list) => {
      if (!stopped && Array.isArray(list) && list.length) accounts(list);
    }).catch(() => undefined);
  };

  const scan = () => {
    if (stopped) return;
    const solana = [win.phantom?.solana, win.solana];
    for (const provider of solana) {
      if (provider && !seen.has(provider)) { seen.add(provider); attachSolana(provider); }
    }
    const evm = win.ethereum ? [win.ethereum, ...(win.ethereum.providers ?? [])] : [];
    for (const provider of evm) {
      if (provider && !seen.has(provider)) { seen.add(provider); attachEvm(provider); }
    }
  };

  // EIP-6963: wallets announce themselves, which also covers pages with several wallets installed.
  const announced = (event: Event) => {
    const provider = (event as CustomEvent<{ provider?: Provider }>).detail?.provider;
    if (provider && !stopped && !seen.has(provider)) { seen.add(provider); attachEvm(provider); }
  };
  window.addEventListener("eip6963:announceProvider", announced);
  undo.push(() => window.removeEventListener("eip6963:announceProvider", announced));
  window.dispatchEvent(new Event("eip6963:requestProvider"));

  // Extensions inject their providers at different times, some after load.
  window.addEventListener("ethereum#initialized", scan);
  undo.push(() => window.removeEventListener("ethereum#initialized", scan));
  scan();
  if (document.readyState !== "complete") {
    window.addEventListener("load", scan, { once: true });
    undo.push(() => window.removeEventListener("load", scan));
  }
  const late = [500, 1500, 4000].map((ms) => setTimeout(scan, ms));
  undo.push(() => late.forEach(clearTimeout));

  return () => {
    stopped = true;
    undo.splice(0).forEach((fn) => fn());
  };
}
