// Wallet awareness without touching the wallet: the SDK only listens to the events injected
// providers already emit. It never wraps, patches or calls signing methods.

type Listener = (address: string, chain: "solana" | "evm") => void;

interface EventfulProvider {
  on?: (event: string, handler: (...args: unknown[]) => void) => void;
  publicKey?: { toString(): string } | null;
  selectedAddress?: string | null;
}

function solanaProvider(): EventfulProvider | undefined {
  const w = window as unknown as { solana?: EventfulProvider; phantom?: { solana?: EventfulProvider } };
  return w.phantom?.solana ?? w.solana;
}

function evmProvider(): EventfulProvider | undefined {
  return (window as unknown as { ethereum?: EventfulProvider }).ethereum;
}

export function watchWallets(onConnect: Listener): void {
  const attach = () => {
    const sol = solanaProvider();
    if (sol?.on) {
      sol.on("connect", (key?: unknown) => {
        const address = (key as { toString?: () => string } | undefined)?.toString?.() ?? sol.publicKey?.toString();
        if (address) onConnect(address, "solana");
      });
      sol.on("accountChanged", (key?: unknown) => {
        const address = (key as { toString?: () => string } | undefined)?.toString?.();
        if (address) onConnect(address, "solana");
      });
      if (sol.publicKey) onConnect(sol.publicKey.toString(), "solana");
    }
    const evm = evmProvider();
    if (evm?.on) {
      evm.on("accountsChanged", (accounts?: unknown) => {
        const first = Array.isArray(accounts) ? String(accounts[0] ?? "") : "";
        if (first) onConnect(first.toLowerCase(), "evm");
      });
      if (evm.selectedAddress) onConnect(evm.selectedAddress.toLowerCase(), "evm");
    }
  };
  // Wallet extensions inject their providers at different times.
  if (document.readyState === "complete") attach();
  else window.addEventListener("load", attach, { once: true });
}
