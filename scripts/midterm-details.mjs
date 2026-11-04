// Dal feed completo ricava un file compatto con le gare di Camera, Senato e governatori
// (usato dai blocchi dello speciale). Riscrive il file solo se qualcosa è cambiato.
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const FEED = process.env.FEED || "https://sitmap.live/api/elections/us-2026.json";
const OUT  = "midterm-details.json";

// Margine Harris − Trump 2024 sui distretti usati nel 2026 (The Downballot), file opzionale accanto allo script
const P24 = existsSync("house-2024.json") ? JSON.parse(readFileSync("house-2024.json", "utf8")) : {};
const AT_LARGE = new Set(["AK", "DE", "ND", "SD", "VT", "WY"]);
const dkey = (st, dist) => st + "-" + (AT_LARGE.has(st) ? "AL" : String(parseInt(dist, 10)).padStart(2, "0"));

const grp = x => x === "dem" ? "d" : x === "rep" ? "r" : x ? "o" : null;
const gr = c => c?.group === "dem" ? "d" : c?.group === "rep" ? "r" : "o";
const r1 = n => Math.round(n * 10) / 10;

function race(c){
  const cands = c.candidates || [];
  const total = cands.reduce((s, x) => s + (x.votes || 0), 0);
  const winId = c.call?.winners?.[0];
  const win = winId != null ? cands.find(x => String(x.id) === String(winId)) : null;
  const top = [...cands].sort((a, b) => (b.votes || 0) - (a.votes || 0))[0];
  const best = g => cands.filter(x => x.group === g).sort((a, b) => (b.votes || 0) - (a.votes || 0))[0];
  const d = best("dem"), r = best("rep");
  const pct = x => x ? (x.pct ?? (total ? x.votes / total * 100 : 0)) : 0;
  const o = {
    s: c.jurisdiction?.state,
    g: gr(win || (total > 0 ? top : null)),           // chi vince / è in testa
    c: win ? 1 : 0,                                    // 1 = chiamata, 0 = in vantaggio
    m: total > 0 ? r1(pct(d) - pct(r)) : null,         // margine Dem − Rep in punti
    rp: Math.round(c.reportingPct ?? 0)
  };
  if (total === 0) o.g = null;
  if (c.chamber === "house"){
    o.n = c.jurisdiction?.district || "AL";
    const k = dkey(o.s, o.n);
    if (P24[k] != null) o.p24 = P24[k];
    if (!d || !r) o.u = 1;                              // un solo partito maggiore in gara: margine non confrontabile
  }
  if (c.special) o.sp = 1;
  if (d) o.dn = d.name; if (r) o.rn = r.name;
  const inc = cands.find(x => x.incumbent); if (inc) o.i = gr(inc);
  return o;
}

const res = await fetch(FEED, { headers: { "user-agent": "midterm-banner-updater" } });
if (!res.ok) throw new Error("HTTP " + res.status);
const json = await res.json();

const prior = id => (json.election?.chambers || []).find(x => x.id === id)?.priorHolder || {};
const pS = prior("senate"), pG = prior("governor");
const by = ch => (json.contests || []).filter(c => c.chamber === ch && !c.jurisdiction?.territory);

const out = { when: json.fetchedAt || json.generatedAt || null, house: [], senate: [], gov: [] };
for (const c of by("house")) out.house.push(race(c));
out.house.sort((a, b) => (b.m ?? -999) - (a.m ?? -999));
for (const c of by("senate")){ const o = race(c); o.p = grp(pS[o.s]); out.senate.push(o); }
for (const c of by("governor")){ const o = race(c); o.p = grp(pG[o.s]); out.gov.push(o); }
const noMatch = out.house.filter(h => h.p24 == null).length;
if (Object.keys(P24).length) console.log("distretti senza dato 2024:", noMatch);
if (out.house.length < 300 || !out.senate.length || !out.gov.length) throw new Error("dati incompleti");

const strip = d => JSON.stringify({ ...d, when: undefined });
if (existsSync(OUT) && strip(JSON.parse(readFileSync(OUT, "utf8"))) === strip(out)) {
  console.log("nessuna novità"); process.exit(0);
}
writeFileSync(OUT, JSON.stringify(out));
console.log("aggiornato", OUT, JSON.stringify(out).length, "byte");
