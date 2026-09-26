#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Notifie un salon Discord via webhook — bibliothèque standard uniquement.

AUCUNE clé dans ce fichier. L'URL du webhook est lue dans cet ordre :
  1. --webhook URL
  2. variable d'environnement  DISCORD_WEBHOOK
  3. fichier local  ~/.ratiss-webhook   (une ligne, jamais commité)

Exemples :
  python3 notifier_discord.py --test
  python3 notifier_discord.py --statut OK --titre "Empreintes 50/50" \\
      --details "0 problème sur 50 fichiers" --lien https://github.com/jonathansearch/RATISS-ARCHIVES
  python3 notifier_discord.py --statut ECHEC --titre "Tests GCR" --details "1 échec sur 4"
  python3 notifier_discord.py --test --dry-run          # n'envoie rien, affiche le JSON

Garde-fou : le message n'autorise AUCUNE mention (@everyone, @here, rôles).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

COULEURS = {"OK": 0x2ECC71, "ECHEC": 0xE74C3C, "INFO": 0x3498DB}
FICHIER_LOCAL = pathlib.Path.home() / ".ratiss-webhook"


def charger_webhook(arg: str | None) -> str:
    if arg:
        return arg.strip()
    env = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if env:
        return env
    if FICHIER_LOCAL.exists():
        return FICHIER_LOCAL.read_text().strip().splitlines()[0]
    sys.exit(
        "✘ Aucun webhook trouvé.\n"
        "  → mets-le dans DISCORD_WEBHOOK, ou dans ~/.ratiss-webhook,\n"
        "  → ou passe --webhook URL.\n"
        "  Jamais dans un fichier suivi par git."
    )


def construire(statut: str, titre: str, details: str, lien: str | None, salon: str | None) -> dict:
    statut = statut.upper()
    entete = {"OK": "✅", "ECHEC": "❌", "INFO": "🔵"}.get(statut, "🔵")
    titre_complet = f"{entete} {titre}" + (f"  ·  {salon}" if salon else "")
    embed: dict = {
        "title": titre_complet[:256],
        "color": COULEURS.get(statut, COULEURS["INFO"]),
        "description": (details or "—")[:4000],
        "footer": {"text": "RATISS LABS · notification automatique"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if lien:
        embed["url"] = lien
    return {
        "embeds": [embed],
        "allowed_mentions": {"parse": []},  # aucune mention possible
    }


def envoyer(webhook: str, charge: dict, dry_run: bool = False) -> int:
    corps = json.dumps(charge, ensure_ascii=False).encode()
    if dry_run:
        print(json.dumps(charge, ensure_ascii=False, indent=1))
        print("\n(dry-run : rien n'a été envoyé)")
        return 0
    req = urllib.request.Request(
        webhook,
        data=corps,
        headers={"Content-Type": "application/json", "User-Agent": "RATISS-LABS-notifier/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"✅ envoyé (HTTP {r.status})")
            return 0
    except urllib.error.HTTPError as e:
        print(f"✘ Discord a refusé : HTTP {e.code} — {e.read()[:300].decode(errors='replace')}")
        return 1
    except Exception as e:  # réseau coupé, etc.
        print(f"✘ envoi impossible : {type(e).__name__} {e}")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description="Notifie un salon Discord (webhook).")
    p.add_argument("--test", action="store_true", help="envoie un message de test")
    p.add_argument("--statut", default=None, help="OK | ECHEC | INFO (défaut : OK en test, INFO sinon)")
    p.add_argument("--titre", default="RATISS LABS")
    p.add_argument("--details", default="")
    p.add_argument("--lien", default=None)
    p.add_argument("--salon", default=None, help="juste affiché dans le titre (pas un routage)")
    p.add_argument("--webhook", default=None)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    if a.test:
        a.titre = a.titre if a.titre != "RATISS LABS" else "Test de connexion"
        a.details = a.details or "Le webhook répond. Le labo peut maintenant pousser ses notifications ici. 🧪"

    webhook = charger_webhook(a.webhook)
    if webhook.startswith("https://discord.com/api/webhooks/") is False and not a.dry_run:
        print("⚠️  l'URL ne ressemble pas à un webhook Discord — envoi quand même.")
    statut = a.statut or ("OK" if a.test else "INFO")
    return envoyer(webhook, construire(statut, a.titre, a.details, a.lien, a.salon), a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
