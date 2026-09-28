export default function PageTabs({ tabs, activeTab, onChange, idPrefix, label = "Page sections" }) {
  function handleKeyDown(event) {
    const buttons = Array.from(event.currentTarget.parentElement?.querySelectorAll('[role="tab"]') ?? []);
    const currentIndex = buttons.indexOf(event.target);
    let nextIndex = currentIndex;

    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % buttons.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = buttons.length - 1;
    else return;

    event.preventDefault();
    buttons[nextIndex]?.focus();
    onChange(tabs[nextIndex].key);
  }

  return (
    <div className="overflow-x-auto border-b border-soc-border" role="tablist" aria-label={label}>
      <div className="flex min-w-max items-center gap-1">
        {tabs.map((tab) => {
          const selected = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              id={`${idPrefix}-tab-${tab.key}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${idPrefix}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.key)}
              onKeyDown={handleKeyDown}
              className={`relative -mb-px border-b-2 px-4 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-soc-electric/50 ${
                selected
                  ? "border-soc-electric text-soc-text"
                  : "border-transparent text-soc-muted hover:border-soc-border hover:text-soc-text"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
