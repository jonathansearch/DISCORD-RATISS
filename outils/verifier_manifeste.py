#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Vérifie les empreintes SHA-256 de MANIFESTE.json. Sortie lisible + code de sortie.

  python3 outils/verifier_manifeste.py            # depuis la racine du dépôt
  python3 outils/verifier_manifeste.py --json     # sortie machine (pour la CI)

Code de sortie : 0 = tout conforme, 1 = au moins un problème.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys


def verifier(racine: pathlib.Path) -> tuple[int, int, list[str]]:
    manifeste = racine / "MANIFESTE.json"
    if not manifeste.exists():
        print("✘ MANIFESTE.json absent")
        return 0, 1, ["MANIFESTE.json absent"]
    m = json.loads(manifeste.read_text())
    fichiers = m.get("fichiers", {})
    ok, ko, soucis = 0, 0, []
    for chemin, attendu in fichiers.items():
        p = racine / chemin
        if not p.exists():
            soucis.append(f"MANQUANT  {chemin}")
            ko += 1
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h == attendu:
            ok += 1
        else:
            soucis.append(f"DIFFÉRENT {chemin}  ({h[:12]}… ≠ {attendu[:12]}…)")
            ko += 1
    return ok, ko, soucis


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="sortie JSON (CI)")
    p.add_argument("--racine", default=".", help="racine du dépôt")
    a = p.parse_args()
    ok, ko, soucis = verifier(pathlib.Path(a.racine).resolve())
    if a.json:
        print(json.dumps({"conformes": ok, "problemes": ko, "detail": soucis}, ensure_ascii=False))
    else:
        for s in soucis:
            print(f"  ✘ {s}")
        print(f"  {ok} fichier(s) conforme(s), {ko} problème(s)")
    return 1 if ko else 0


if __name__ == "__main__":
    raise SystemExit(main())
