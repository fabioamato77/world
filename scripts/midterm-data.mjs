// Scarica il feed completo di sitmap.live e salva solo i numeri che servono al banner.
// Non riscrive il file se i numeri non sono cambiati (così niente commit inutili).
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const FEED = process.env.FEED || "https://sitmap.live/api/elections/us-2026.json";
const OUT  = "midterm-data.json";

const CH = {
  cam: { id: "house",    total: 435, maj: 218 },
  sen: { id: "senate",   total: 100, maj: 51  },
  gov: { id: "governor", total: 50,  maj: 26  }
};

function parse(json){
  if (json && json.cam && json.sen) return json;   /* file leggero già pronto (midterm-data.json) */
  const out = {};
  for (const [k, c] of Object.entries(CH)){
    const t = (json.tallies || []).find(x => x.chamber === c.id);
    if (!t) continue;
    out[k] = {
      d:  t.control?.dem ?? 0,
      r:  t.control?.rep ?? 0,
      dl: t.leading?.dem ?? 0,
      rl: t.leading?.rep ?? 0
    };
    if (k === "gov") out.govInfo = { up: t.contests ?? 0, called: t.called ?? 0 };
  }

  /* governatori che cambiano partito: vincitore chiamato vs partito prima del voto (solo i 50 Stati) */
  const gc = (json.election?.chambers || []).find(x => x.id === "governor");
  if (gc?.priorHolder){
    const flips = { dem: 0, rep: 0 };
    for (const c of json.contests || []){
      if (c.chamber !== "governor" || c.jurisdiction?.territory) continue;
      const w = c.call?.winners?.[0];
      if (w == null) continue;
      const cand = (c.candidates || []).find(x => String(x.id) === String(w));
      const was = gc.priorHolder[c.jurisdiction?.state];
      if (cand && was && cand.group !== was && (cand.group === "dem" || cand.group === "rep")) flips[cand.group]++;
    }
    out.flips = flips;
  }

  out.when = json.fetchedAt || json.generatedAt || null;
  return out;
}

const r = await fetch(FEED, { headers: { "user-agent": "midterm-banner-updater" } });
if (!r.ok) throw new Error("HTTP " + r.status);
const data = parse(await r.json());
if (!data.cam || !data.sen) throw new Error("formato inatteso");

const strip = d => JSON.stringify({ ...d, when: undefined });
if (existsSync(OUT) && strip(JSON.parse(readFileSync(OUT, "utf8"))) === strip(data)) {
  console.log("nessuna novità"); process.exit(0);
}
writeFileSync(OUT, JSON.stringify(data));
console.log("aggiornato", OUT);
