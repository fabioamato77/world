#!/usr/bin/env python3
"""
Genera spagna-data.json per il banner "La Spagna al voto" da QUALSIASI fonte.

Uso:
  python aggiorna_dati.py                 # legge fonte.json, scrive spagna-data.json
  python aggiorna_dati.py --inspect       # mostra cosa trova nella fonte (per capire le chiavi)
  python aggiorna_dati.py --dry-run       # stampa il risultato senza scrivere
  python aggiorna_dati.py --config altro.json

Come funziona (tre strati, indipendenti dalla fonte):
  1. LETTURA   url/file, JSON o CSV (auto-detect dal contenuto).
  2. ESTRAZIONE trova la lista "partito -> seggi". In 'auto' cerca da solo la lista di record
     con un campo-nome e un campo-seggi (nomi tipici: siglas/partido/party/name, escanos/seats/diputados...).
     Se la fonte è strana, si forzano percorso e chiavi in fonte.json.
  3. NORMALIZZAZIONE raggruppa nei 4 partiti del banner + Altri, controlla la coerenza e scrive.

Sicurezza: se la fonte non risponde, i dati non tornano o i numeri sono incoerenti,
il file di uscita NON viene toccato (il banner continua a mostrare l'ultimo dato buono).
Solo libreria standard.
"""
import argparse, csv, io, json, re, sys, unicodedata, urllib.request
from datetime import datetime, timezone, timedelta

NOME_KEYS = ["siglas", "sigla", "acronimo", "partido", "candidatura", "nombre", "party", "name", "id", "label", "codigo"]
SEGGI_KEYS = ["escanos", "escaños", "esc", "seats", "diputados", "senadores", "elegidos", "won", "total_seats", "escanos_totales", "numescanos", "n_escanos"]
PCT_KEYS = ["pctvotos", "pctvotes", "porcentaje", "pct", "percent", "percentage", "votospct", "pct_votos"]
SCRUT_KEYS = ["escrutado", "pctescrutado", "porcentajeescrutado", "scrutinized", "counted", "countedpercent", "pct_escrutado", "mesasescrutadas", "porcentaje_escrutado"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]", "", s)).strip()


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace("%", "").replace(" ", "")
    if re.fullmatch(r"-?\d+(\.\d{3})+", s): s = s.replace(".", "")          # 1.234 -> 1234
    elif re.fullmatch(r"-?\d+,\d+", s): s = s.replace(",", ".")              # 62,4 -> 62.4
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


# ---------- 1. lettura ----------
def leggi(cfg_blocco, http):
    if cfg_blocco.get("file"):
        raw = open(cfg_blocco["file"], "rb").read()
    elif cfg_blocco.get("url"):
        req = urllib.request.Request(cfg_blocco["url"], headers=http)
        raw = urllib.request.urlopen(req, timeout=20).read()
    else:
        return None
    text = raw.decode("utf-8-sig", errors="replace")
    fmt = cfg_blocco.get("formato", "auto")
    if fmt == "auto":
        fmt = "json" if text.lstrip()[:1] in "[{" else "csv"
    if fmt == "json":
        return json.loads(text)
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|") if text.strip() else csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


# ---------- 2. estrazione ----------
def scendi(obj, percorso):
    for p in [x for x in re.split(r"[./]", percorso) if x]:
        obj = obj[int(p)] if isinstance(obj, list) else obj[p]
    return obj


def trova_liste(obj, path=""):
    """Tutte le liste di dict con >=2 elementi."""
    if isinstance(obj, list):
        if len(obj) >= 2 and all(isinstance(x, dict) for x in obj):
            yield path, obj
        for i, x in enumerate(obj):
            yield from trova_liste(x, f"{path}.{i}" if path else str(i))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from trova_liste(v, f"{path}.{k}" if path else k)


def scegli_chiave(record, candidati, forzata=""):
    if forzata:
        return forzata if forzata in record else None
    low = {k.lower().replace("_", "").replace(" ", ""): k for k in record}
    for c in candidati:
        c2 = c.replace("_", "")
        if c2 in low:
            return low[c2]
    return None


def estrai(dati, blocco, parola):
    """Ritorna (percorso, [(nome, seggi)]) per la camera indicata. parola = 'congreso'|'senado'."""
    if blocco.get("percorso"):
        try: liste = [(blocco["percorso"], scendi(dati, blocco["percorso"]))]
        except (KeyError, IndexError, TypeError, ValueError): return None, []
    else:
        liste = list(trova_liste(dati))
        # preferisce le liste il cui percorso contiene la parola della camera
        liste.sort(key=lambda t: (parola not in norm(t[0]).replace(" ", ""), -len(t[1])))
    for path, lst in liste:
        if not lst: continue
        kn = scegli_chiave(lst[0], NOME_KEYS, blocco.get("chiave_nome", ""))
        ks = scegli_chiave(lst[0], SEGGI_KEYS, blocco.get("chiave_seggi", ""))
        if not kn or not ks: continue
        kp = scegli_chiave(lst[0], PCT_KEYS, blocco.get("chiave_pct", ""))
        righe = [(str(r.get(kn)), num(r.get(ks)), num(r.get(kp)) if kp else None) for r in lst]
        righe = [(n, s, p) for n, s, p in righe if s is not None]
        if len(righe) >= 2:
            return path, righe
    return None, []


def cerca_scrutinio(dati, percorso=""):
    if percorso:
        try: return num(scendi(dati, percorso))
        except (KeyError, IndexError, TypeError, ValueError): return None
    def rec(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if norm(k).replace(" ", "").replace("-", "") in SCRUT_KEYS and num(v) is not None:
                    return num(v)
            for v in o.values():
                r = rec(v)
                if r is not None: return r
        elif isinstance(o, list):
            for v in o[:50]:
                r = rec(v)
                if r is not None: return r
    return rec(dati)


# ---------- 3. normalizzazione ----------
def raggruppa(righe, gruppi, ordine=None):
    alias = {norm(a): g for g, lst in gruppi.items() for a in lst + [g]}
    tot = {g: 0 for g in gruppi}
    tot["Altri"] = 0
    pct = {g: 0.0 for g in tot}
    haspct = all(p is not None for _, _, p in righe)
    for nome, seggi, p in righe:
        g = alias.get(norm(nome), "Altri")
        tot[g] += int(seggi)
        if haspct: pct[g] += p
    return tot, (pct if haspct else None)


def costruisci(tot, colori, totale, maggioranza, ordine=None, pct=None):
    ids = ordine or [k for k in tot if k != "Altri"] + ["Altri"]
    if ordine:  # camere con meno gruppi: il resto confluisce in Altri
        extra = sum(v for k, v in tot.items() if k not in ordine)
        tot = {**{k: tot.get(k, 0) for k in ordine}}
        tot["Altri"] = tot.get("Altri", 0) + extra
    parties = []
    for k in ids:
        d = {"id": k, "seats": tot.get(k, 0)}
        if pct is not None: d["pct"] = round(pct.get(k, 0.0), 1)
        d["color"] = colori.get(k, "#aaa59a")
        parties.append(d)
    return {"total": totale, "majority": maggioranza, "parties": parties}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="fonte.json")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    http = cfg.get("intestazioni_http", {})

    out, log = {"mode": "live"}, []
    scr, vecchio = None, {}
    try: vecchio = json.load(open(cfg["uscita"], encoding="utf-8"))
    except Exception: pass

    for chiave, parola, tot_k in (("congress", "congreso", "congreso"), ("senate", "senado", "senado")):
        blocco = cfg[tot_k]
        try:
            dati = leggi(blocco, http)
        except Exception as e:
            log.append(f"{parola}: fonte non raggiungibile ({e})"); continue
        if dati is None:
            continue
        path, righe = estrai(dati, blocco, parola)
        if a.inspect:
            print(f"== {parola}: percorso={path!r}, {len(righe)} righe")
            for n, s, p in righe[:25]: print(f"   {n!r:40} {s}  {p if p is not None else ''}")
            if not righe:
                print("   (nessuna lista partito/seggi trovata: elenco liste candidate)")
                for p, l in list(trova_liste(dati))[:15]: print("   ", p, list(l[0].keys())[:8])
        if scr is None:
            scr = cerca_scrutinio(dati, cfg["scrutinio"].get("percorso", ""))
        if not righe:
            log.append(f"{parola}: nessuna lista partito/seggi riconosciuta"); continue
        tot, pct = raggruppa(righe, cfg.get("gruppi_senato", cfg["gruppi"]) if chiave == "senate" else cfg["gruppi"])
        if chiave == "senate": pct = None      # al Senato la % di voto non è confrontabile
        ordine = cfg["ordine_senato"] if chiave == "senate" else None
        totale = cfg["totali"][chiave]
        somma = sum(tot.values())
        if totale and somma > totale:
            log.append(f"{parola}: somma seggi {somma} > totale {totale}, scarto"); continue
        out[chiave] = costruisci(tot, cfg["colori"], totale or None, cfg["maggioranza"][chiave], ordine, pct)
        out[chiave]["_assegnati"] = somma

    if "congress" not in out:
        print("NESSUN AGGIORNAMENTO:", "; ".join(log) or "fonte non configurata", file=sys.stderr)
        sys.exit(0 if not a.inspect else 0)
    if sum(x["seats"] for x in out["congress"]["parties"]) == 0 and not scr:
        print("NESSUN AGGIORNAMENTO: ancora nessun seggio assegnato e 0% scrutinato", file=sys.stderr); sys.exit(0)
    if "senate" not in out and vecchio.get("senate"):
        out["senate"] = vecchio["senate"]          # tiene l'ultimo dato buono del Senato
    out["updated"] = datetime.now(timezone(timedelta(hours=1))).isoformat(timespec="seconds")
    out["scrutinized"] = scr if scr is not None else vecchio.get("scrutinized")
    for c in ("congress", "senate"):
        if c in out: out[c].pop("_assegnati", None)

    testo = json.dumps(out, ensure_ascii=False, indent=2)
    if a.dry_run or a.inspect:
        print(testo); 
    else:
        open(cfg["uscita"], "w", encoding="utf-8").write(testo + "\n")
        print("scritto", cfg["uscita"], "|", "; ".join(log) or "ok")
    for l in log: print("avviso:", l, file=sys.stderr)


if __name__ == "__main__":
    main()
