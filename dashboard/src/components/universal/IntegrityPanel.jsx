import { useEffect, useMemo, useState } from "react";
import { fetchIntegrity } from "../../services/universalApi";
import { EmptyState, StatTile, shortId } from "./shared";

const GREEN = "#3cc28f";
const RED = "#ef5b67";
const SURFACE = "#111726";

/** Real participants on the left; accounts linked into a farm on a ring around what they share. */
function FarmGraph({ people, farm, linkLabel }) {
  const [hover, setHover] = useState(null);
  const width = 1200;
  const cols = 22;
  const rows = Math.max(1, Math.ceil(people.length / cols));
  const height = Math.max(300, 70 + rows * 22);
  const ringR = Math.min(105, 40 + farm.length * 2.2);
  const cx = 880;
  const cy = height / 2 + 10;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto w-full max-w-[1200px]" role="img"
        aria-label={`${people.length} real participants and ${farm.length} accounts linked into a farm`}>
        <text x="24" y="28" fill="#e6ebf4" fontSize="13" fontWeight="600">Real participants · {people.length}</text>
        {people.map((id, i) => (
          <circle key={id} cx={36 + (i % cols) * 22} cy={52 + Math.floor(i / cols) * 22} r="6" fill={GREEN}
            stroke={SURFACE} strokeWidth="2" onMouseEnter={() => setHover({ id, kind: "Real participant" })}
            onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
            <title>{id}</title>
          </circle>
        ))}

        <text x={cx} y="28" textAnchor="middle" fill="#e6ebf4" fontSize="13" fontWeight="600">
          Linked into a farm · {farm.length}
        </text>
        {farm.length ? (
          <g>
            {farm.map((id, i) => {
              const angle = (2 * Math.PI * i) / farm.length - Math.PI / 2;
              return <line key={`l-${id}`} x1={cx} y1={cy} x2={cx + ringR * Math.cos(angle)} y2={cy + ringR * Math.sin(angle)}
                stroke="#2a3448" strokeWidth="1" />;
            })}
            <circle cx={cx} cy={cy} r="30" fill={SURFACE} stroke="#8a96ab" strokeWidth="1.25" />
            <text x={cx} y={cy - 2} textAnchor="middle" fill="#e6ebf4" fontSize="10.5" fontWeight="600">shared</text>
            <text x={cx} y={cy + 11} textAnchor="middle" fill="#8a96ab" fontSize="10.5">{linkLabel}</text>
            {farm.map((id, i) => {
              const angle = (2 * Math.PI * i) / farm.length - Math.PI / 2;
              return (
                <circle key={id} cx={cx + ringR * Math.cos(angle)} cy={cy + ringR * Math.sin(angle)} r="6" fill={RED}
                  stroke={SURFACE} strokeWidth="2" onMouseEnter={() => setHover({ id, kind: "Linked account, reward withheld" })}
                  onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
                  <title>{id}</title>
                </circle>
              );
            })}
          </g>
        ) : (
          <text x={cx} y={cy} textAnchor="middle" fill="#8a96ab" fontSize="12">No linked accounts</text>
        )}
      </svg>
      {hover ? (
        <div className="pointer-events-none absolute right-3 top-3 rounded-md border border-soc-border bg-soc-panel px-3 py-2 text-xs shadow-panel">
          <p className="text-soc-muted">{hover.kind}</p>
          <p className="font-mono text-soc-text">{shortId(hover.id)}</p>
        </div>
      ) : null}
    </div>
  );
}

export default function IntegrityPanel({ verdicts }) {
  const campaigns = useMemo(() => {
    const ids = [];
    verdicts.forEach((v) => {
      if (["campaign", "raise", "token"].includes(v.resource?.type) && !ids.includes(v.resource.id)) ids.push(v.resource.id);
    });
    return ids;
  }, [verdicts]);
  const [selected, setSelected] = useState(null);
  const resource = selected && campaigns.includes(selected) ? selected : campaigns[0];
  const [data, setData] = useState(null);
  const latestId = verdicts[0]?.verdict_id;

  useEffect(() => {
    if (!resource) return undefined;
    let active = true;
    const load = () => fetchIntegrity(resource).then((d) => active && setData(d)).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, [resource, latestId]);

  const linkLabel = useMemo(() => {
    const farmVerdict = verdicts.find((v) => v.verdict === "bot_farm" && v.resource?.id === resource);
    const kinds = Object.keys(farmVerdict?.linked_by || {});
    if (kinds.includes("funded_by")) return "funding wallet";
    if (kinds.includes("device_hash")) return "device";
    if (kinds.length) return "IP + timing";
    return "traits";
  }, [verdicts, resource]);

  if (!resource) {
    return (
      <EmptyState title="No campaigns yet">
        Campaign integrity appears once a site sends campaign, raise or token events. Try the example campaign in <code>sdk/examples/rewards-campaign</code>.
      </EmptyState>
    );
  }

  const people = data?.human_accounts || [];
  const farm = data?.flagged_accounts || [];
  const claims = data?.claims || { paid: 0, withheld: 0, amount_withheld: 0 };

  return (
    <section className="soc-glass p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="soc-section-title">Campaign integrity</h2>
          <p className="text-xs text-soc-muted">Who is really claiming rewards. Linked accounts are shadowed: they see “pending review” and are never paid.</p>
        </div>
        {campaigns.length > 1 ? (
          <select className="soc-btn" value={resource} onChange={(e) => setSelected(e.target.value)} aria-label="Campaign">
            {campaigns.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        ) : <span className="font-mono text-xs text-soc-muted">{resource}</span>}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Participants" value={data?.participants ?? "–"} />
        <StatTile label="Real people" value={data?.human ?? "–"} tone="text-soc-green" />
        <StatTile label="Flagged accounts" value={data?.flagged ?? "–"} tone="text-soc-red" />
        <StatTile label="Claims paid" value={claims.paid} />
        <StatTile label="Claims withheld" value={claims.withheld} tone="text-soc-amber" />
        <StatTile label="Rewards withheld" value={Math.round(claims.amount_withheld).toLocaleString()} hint="tokens not paid to bots" />
      </div>

      <div className="soc-inset mt-4 overflow-x-auto p-3">
        <div className="min-w-[720px]">
          <FarmGraph people={people} farm={farm} linkLabel={linkLabel} />
        </div>
      </div>
    </section>
  );
}
