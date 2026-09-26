#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""RATISS LABS — agent du hub Discord.

Point d'entrée appelé par .github/workflows/agent.yml. Volontairement AUTONOME :
un point d'entrée de CI ne doit dépendre d'aucun fichier voisin pour démarrer.

Le secret arrive par variable d'environnement — jamais en argument, jamais écrit
sur disque, jamais affiché. Deux noms acceptés, dans cet ordre :
  1. `DISCORD_WEBHOOK_URL`   (nom explicite, posé par agent.yml)
  2. `RATISS`                (nom historique, conservé pour compatibilité)

Trois usages :

  python3 agent.py                 # RAPPORT : vérifie RATISS-ARCHIVES et poste le verdict
  python3 agent.py --test          # message de connexion
  python3 agent.py --titre "…" --details "…" --statut OK --lien "…"
  python3 agent.py … --dry-run     # n'envoie rien, affiche le JSON

Codes de sortie : 0 = message envoyé · 1 = problème (secret, réseau, envoi)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEPOT_ARCHIVES = "RATISS-ARCHIVES"        # dépôt vérifié par le rapport
PROPRIETAIRE = "jonathansearch"
COULEURS = {"OK": 0x2ECC71, "ECHEC": 0xE74C3C, "INFO": 0x3498DB}
PREFIXES_WEBHOOK = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")


# ───────────────────────────── 1. le secret ─────────────────────────────

NOMS_SECRET = ("DISCORD_WEBHOOK_URL", "RATISS")


def lire_secret() -> str:
    for nom in NOMS_SECRET:
        valeur = os.environ.get(nom, "").strip()
        if valeur:
            break
    else:
        valeur = ""
    if not valeur:
        sys.exit(
            "✘ Aucun webhook trouvé.\n"
            f"  variables cherchées : {' puis '.join(NOMS_SECRET)}\n"
            "  GitHub → Settings → Secrets and variables → Actions → RATISS"
        )
    if not valeur.startswith(PREFIXES_WEBHOOK):
        # cas probable : on a mis un token GitHub là où il faut un webhook Discord
        debut = valeur.split("/")[2] if "//" in valeur else valeur[:12]
        sys.exit(
            f"✘ Le secret ({' / '.join(NOMS_SECRET)}) n'est pas une URL de webhook Discord.\n"
            f"  valeur vue : {debut}… (le reste est masqué)\n"
            "  attendu : https://discord.com/api/webhooks/<id>/<jeton>\n"
            "  Où le trouver : Discord → clic droit sur le salon → Modifier le salon →\n"
            "                 Intégrations → Webhooks → Nouveau webhook → Copier l'URL."
        )
    return valeur


# ───────────────────────────── 2. l'envoi ──────────────────────────────

def construire(statut: str, titre: str, details: str, lien: str | None) -> dict:
    statut = statut.upper()
    entete = {"OK": "✅", "ECHEC": "❌"}.get(statut, "🔵")
    embed: dict = {
        "title": f"{entete} {titre}"[:256],
        "color": COULEURS.get(statut, COULEURS["INFO"]),
        "description": (details or "—")[:4000],
        "footer": {"text": "RATISS LABS · agent du hub"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if lien:
        embed["url"] = lien
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}  # aucune mention possible


def envoyer(webhook: str, charge: dict, dry_run: bool = False) -> int:
    if dry_run:
        print(json.dumps(charge, ensure_ascii=False, indent=1))
        print("(dry-run : rien n'a été envoyé)")
        return 0
    req = urllib.request.Request(
        webhook,
        data=json.dumps(charge, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "RATISS-LABS-agent/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            print(f"✅ message envoyé (HTTP {r.status})")
            return 0
    except urllib.error.HTTPError as e:
        corps = e.read()[:300].decode(errors="replace")
        print(f"✘ Discord a refusé : HTTP {e.code} — {corps}")
        if e.code in (401, 404):
            print("  → le webhook a probablement été supprimé ou révoqué. Recrée-le et mets RATISS à jour.")
        return 1
    except Exception as e:
        print(f"✘ envoi impossible : {type(e).__name__} {e}")
        return 1


# ───────────────────────── 3. le rapport (le vrai travail) ─────────────────────────

def verifier_manifeste(racine: pathlib.Path) -> dict:
    """Vérifie les empreintes SHA-256 d'un MANIFESTE.json. Autonome (pas d'import voisin)."""
    manifeste = racine / "MANIFESTE.json"
    if not manifeste.exists():
        return {"conformes": 0, "problemes": 1, "detail": ["MANIFESTE.json absent du dépôt cloné"]}
    data = json.loads(manifeste.read_text())
    ok, ko, detail = 0, 0, []
    for chemin, attendu in data.get("fichiers", {}).items():
        p = racine / chemin
        if not p.exists():
            detail.append(f"MANQUANT {chemin}")
            ko += 1
        elif hashlib.sha256(p.read_bytes()).hexdigest() == attendu:
            ok += 1
        else:
            detail.append(f"DIFFÉRENT {chemin}")
            ko += 1
    return {"conformes": ok, "problemes": ko, "detail": detail}


def cloner(depot: str, dossier: pathlib.Path) -> bool:
    url = f"https://github.com/{PROPRIETAIRE}/{depot}"
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "-q", url, str(dossier)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"✘ clone impossible : {url}\n  {r.stderr.strip()[:200]}")
        return False
    return True


def rapport(dry_run: bool, webhook: str) -> int:
    travail = pathlib.Path(tempfile.mkdtemp(prefix="ratiss-agent-"))
    try:
        cible = travail / DEPOT_ARCHIVES
        if not cloner(DEPOT_ARCHIVES, cible):
            return envoyer(webhook, construire(
                "ECHEC", "Clone impossible",
                f"https://github.com/{PROPRIETAIRE}/{DEPOT_ARCHIVES} est injoignable depuis le runner.",
                f"https://github.com/{PROPRIETAIRE}/{DEPOT_ARCHIVES}"), dry_run)

        res = verifier_manifeste(cible)
        n, ko = res["conformes"], res["problemes"]
        if ko:
            statut = "ECHEC"
            titre = f"{ko} empreinte(s) non conforme(s)"
            details = " · ".join(res["detail"][:8])
        else:
            statut = "OK"
            titre = f"{n}/{n} empreintes conformes"
            details = "0 problème · vérifié depuis le hub Discord · RATISS-ARCHIVES"
        lien = f"https://github.com/{PROPRIETAIRE}/{DEPOT_ARCHIVES}"
        print(f"[rapport] {statut} — {titre}")
        return envoyer(webhook, construire(statut, titre, details, lien), dry_run)
    finally:
        shutil.rmtree(travail, ignore_errors=True)


# ───────────────────────────────── main ─────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Agent du hub Discord RATISS LABS.")
    p.add_argument("--test", action="store_true", help="message de connexion")
    p.add_argument("--titre", default=None)
    p.add_argument("--details", default=None)
    p.add_argument("--statut", default=None, help="OK | ECHEC | INFO")
    p.add_argument("--lien", default=None)
    p.add_argument("--dry-run", action="store_true", help="n'envoie rien")
    a = p.parse_args()

    webhook = "https://discord.com/api/webhooks/0/0" if a.dry_run and not any(
        os.environ.get(n, "").strip() for n in NOMS_SECRET) else lire_secret()

    if a.test:
        return envoyer(webhook, construire(
            "OK", "Test de connexion",
            "Le webhook est bien reconnu, et l'agent du hub sait écrire ici. 🧪\n"
            "Prochaines étapes : bouton « Run workflow » → rapport des empreintes de RATISS-ARCHIVES.",
            None), a.dry_run)

    if a.titre:  # message manuel, entièrement piloté depuis le bouton
        return envoyer(webhook, construire(
            a.statut or "INFO", a.titre, a.details or "", a.lien), a.dry_run)

    return rapport(a.dry_run, webhook)   # défaut : le rapport d'empreintes


if __name__ == "__main__":
    raise SystemExit(main())
