#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""RATISS LABS — agent du hub Discord.

Point d'entrée appelé par .github/workflows/agent.yml. Volontairement AUTONOME :
un point d'entrée de CI ne doit dépendre d'aucun fichier voisin pour démarrer.

Le secret arrive par variable d'environnement — jamais en argument, jamais écrit
sur disque, jamais affiché. Deux noms acceptés, dans cet ordre :
  1. `DISCORD_WEBHOOK_URL`   (nom explicite, posé par agent.yml)
  2. `RATISS`                (nom historique, conservé pour compatibilité)

Quatre usages :

  python3 agent.py                 # RAPPORT : vérifie RATISS-ARCHIVES et poste le verdict
  python3 agent.py --test          # message de connexion
  python3 agent.py --titre "…" --details "…" --statut OK --lien "…"
  python3 agent.py --salon general --titre "…" # choisit le webhook du salon
  python3 agent.py --purger        # supprime les messages postés par l'agent
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
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEPOT_ARCHIVES = "RATISS-ARCHIVES"        # dépôt vérifié par le rapport
PROPRIETAIRE = "jonathansearch"
COULEURS = {"OK": 0x2ECC71, "ECHEC": 0xE74C3C, "INFO": 0x3498DB}
PREFIXES_WEBHOOK = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")


# ───────────────────────────── 1. le secret ─────────────────────────────

NOMS_SECRET = ("DISCORD_WEBHOOK_URL", "RATISS")
SECRET_MULTI_SALONS = "DISCORD_WEBHOOKS_JSON"
SECRETS_SERIE = ("RATISS",) + tuple(f"RATISS{i}" for i in range(2, 24))


def valider_webhook(valeur: str, origine: str) -> str:
    """Valide un webhook sans jamais afficher sa valeur complète."""
    valeur = valeur.strip()
    if not valeur.startswith(PREFIXES_WEBHOOK):
        sys.exit(
            f"✘ Le webhook associé à « {origine} » n'est pas une URL Discord valide.\n"
            "  attendu : https://discord.com/api/webhooks/<id>/<jeton>"
        )
    return valeur


def lire_webhooks(salon: str | None) -> list[str]:
    """Lit le routage multi-salons, avec repli sur l'ancien secret unique."""
    multi = os.environ.get(SECRET_MULTI_SALONS, "").strip()
    if salon == "all" and not multi:
        valeurs = [os.environ[n].strip() for n in SECRETS_SERIE if os.environ.get(n, "").strip()]
        if not valeurs:
            sys.exit("✘ Aucun secret RATISS à RATISS23 n'est configuré.")
        return [valider_webhook(v, "RATISS…") for v in valeurs]
    if salon and multi:
        try:
            routes = json.loads(multi)
        except json.JSONDecodeError:
            sys.exit(f"✘ {SECRET_MULTI_SALONS} n'est pas un JSON valide.")
        if not isinstance(routes, dict):
            sys.exit(f"✘ {SECRET_MULTI_SALONS} doit être un objet JSON nom → webhook.")
        valeurs = list(routes.values()) if salon == "all" else [routes.get(salon)]
        if not valeurs or any(not isinstance(v, str) or not v.strip() for v in valeurs):
            disponibles = ", ".join(sorted(str(k) for k in routes)[:20]) or "aucun"
            sys.exit(f"✘ Salon inconnu : « {salon} ». Salons configurés : {disponibles}")
        return [valider_webhook(v, salon) for v in valeurs]
    return [lire_secret()]


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


def envoyer_a_tous(webhooks: list[str], charge: dict, dry_run: bool = False) -> int:
    """Envoie le même message à chaque webhook configuré."""
    codes = [envoyer(webhook, charge, dry_run) for webhook in webhooks]
    return 0 if all(code == 0 for code in codes) else 1


# ─────────────────────────── 2bis. la purge ────────────────────────────

GARDE_FOU_PURGE = 10   # maximum de messages supprimés par salon et par run


def purger() -> int:
    """Supprime les messages postés par l'agent, salon par salon.

    Un webhook ne peut supprimer que SES propres messages : les messages
    écrits par le chef ne sont jamais touchés. Endpoint utilisé :
    GET/DELETE /messages/@original — le dernier message du webhook.
    Aucune URL, aucune valeur de secret n'est jamais affichée.
    """
    total, actifs, problemes = 0, 0, 0
    for nom in SECRETS_SERIE:
        valeur = os.environ.get(nom, "").strip()
        if not valeur:
            print(f"  · {nom} : secret absent, sauté")
            continue
        if not valeur.startswith(PREFIXES_WEBHOOK):
            print(f"  ⚠ {nom} : secret non reconnu comme webhook Discord, sauté")
            problemes += 1
            continue
        actifs += 1
        supprimes = 0
        for _ in range(GARDE_FOU_PURGE):
            # 1) lire le dernier message du webhook (@original)
            try:
                req = urllib.request.Request(
                    valeur + "/messages/@original",
                    headers={"User-Agent": "RATISS-LABS-agent/1.0"}, method="GET")
                with urllib.request.urlopen(req, timeout=25) as r:
                    identifiant = json.loads(r.read()).get("id")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break   # plus rien à supprimer ici — salon propre
                print(f"  ⚠ {nom} : lecture du dernier message → HTTP {e.code}")
                problemes += 1
                break
            except Exception as e:
                print(f"  ⚠ {nom} : erreur réseau {type(e).__name__}")
                problemes += 1
                break
            # 2) le supprimer
            try:
                req = urllib.request.Request(
                    valeur + f"/messages/{identifiant}",
                    headers={"User-Agent": "RATISS-LABS-agent/1.0"}, method="DELETE")
                with urllib.request.urlopen(req, timeout=25) as r:
                    if r.status == 204:
                        supprimes += 1
                        total += 1
            except urllib.error.HTTPError as e:
                print(f"  ⚠ {nom} : suppression du message {identifiant} → HTTP {e.code}")
                problemes += 1
                break
            except Exception as e:
                print(f"  ⚠ {nom} : erreur réseau {type(e).__name__}")
                problemes += 1
                break
        print(f"  · {nom} : {supprimes} message(s) supprimé(s)")
        time.sleep(0.3)
    verdict = f"═══ Purge : {total} message(s) supprimé(s) sur {actifs} salon(s) actif(s)"
    if problemes:
        verdict += f" · {problemes} problème(s)"
    print(verdict + " ═══")
    return 0 if problemes == 0 else 1


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
    p.add_argument("--salon", default=None, help="clé logique du salon dans DISCORD_WEBHOOKS_JSON")
    p.add_argument("--purger", action="store_true",
                   help="supprime les messages postés par l'agent (jamais ceux du chef)")
    p.add_argument("--dry-run", action="store_true", help="n'envoie rien")
    a = p.parse_args()

    if a.purger:
        return purger()   # la purge balaie tous les secrets configurés

    webhooks = (
        ["https://discord.com/api/webhooks/0/0"]
        if a.dry_run and not (a.salon and os.environ.get(SECRET_MULTI_SALONS, "").strip())
        and not any(os.environ.get(n, "").strip() for n in NOMS_SECRET)
        else lire_webhooks(a.salon)
    )

    if a.test:
        return envoyer_a_tous(webhooks, construire(
            "OK", "Test de connexion",
            "Le webhook est bien reconnu, et l'agent du hub sait écrire ici. 🧪\n"
            "Prochaines étapes : bouton « Run workflow » → rapport des empreintes de RATISS-ARCHIVES.",
            None), a.dry_run)

    if a.titre:  # message manuel, entièrement piloté depuis le bouton
        return envoyer_a_tous(webhooks, construire(
            a.statut or "INFO", a.titre, a.details or "", a.lien), a.dry_run)

    return rapport(a.dry_run, webhook)   # défaut : le rapport d'empreintes


if __name__ == "__main__":
    raise SystemExit(main())
