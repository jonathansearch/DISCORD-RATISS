# 🛰️ DISCORD-RATISS — le hub de notification du labo

> Ce dépôt ne contient **pas** de science. Il contient la **tuyauterie** :
> ce qui permet au labo de pousser ses résultats dans Discord tout seul.

**Licence MIT · RATISS LABS · Yaoundé 🇨🇲**

---

## Ce qu'il fait

| Déclencheur | Ce qui se passe |
|---|---|
| **Manuel** — Actions → *Notification RATISS* → Run workflow | envoie le message que tu écris (statut, titre, détail, lien) |
| **Tous les jours à 08:00 UTC** | vérifie les 55 empreintes de `RATISS-ARCHIVES` et poste le verdict |
| **Appelé par un autre dépôt** (`repository_dispatch`) | n'importe quel dépôt peut demander un message ici |

Sortie type :
> ✅ **55/55 empreintes conformes** · 0 problème · vérifié automatiquement

---

## Le secret

Un seul secret suffit. Deux noms acceptés, dans cet ordre :

1. **`RATISS`** ← déjà créé
2. `DISCORD_WEBHOOK`

> 🔐 **Ce qu'est un secret GitHub :** une valeur chiffrée que **personne ne peut relire** — pas même le propriétaire, pas même après l'avoir enregistrée. C'est le principe. On ne peut que **l'utiliser** dans un workflow.
> Donc : si le secret `RATISS` contient bien **l'URL du webhook Discord** (celle qui commence par `https://discord.com/api/webhooks/…`), **rien d'autre à faire**. Sinon → le workflow te le dira en clair dans le journal.

**Loi n°5 du labo :** aucun token, aucune clé, aucun webhook dans un fichier suivi par git. Jamais.

---

## Vérifier en 30 secondes, depuis ta machine

```bash
cd DISCORD-RATISS
python3 outils/notifier_discord.py --test          # envoie le message de test
python3 outils/notifier_discord.py --test --dry-run  # affiche le JSON sans envoyer
```

Sans webhook dans l'environnement, il lit `~/.ratiss-webhook` (une ligne, `chmod 600`).

**Garde-fou intégré :** le message **ne peut pas** mentionner `@everyone` ni un rôle — c'est verrouillé dans le script (`allowed_mentions: {parse: []}`).

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `.github/workflows/notifier.yml` | le hub : manuel + quotidien + appelable |
| `outils/notifier_discord.py` | envoie un embed ✅/❌/🔵 — bibliothèque standard seule, zéro dépendance |
| `outils/verifier_manifeste.py` | vérifie les empreintes SHA-256 d'un `MANIFESTE.json` |

---

## Les autres dépôts

Les dépôts de code (`GCR`, `RATISS-QVM`, `RATISS-NAVIER`…) ont leur propre modèle de workflow :
**`RATISS-ARCHIVES/discord/CI-modele-tests-depots.yml`** — il lance `pytest`, puis poste le résultat ici.
Il recrée `/home/user` dans le runner GitHub pour respecter les chemins absolus des dépôts.

→ Il leur suffit d'avoir le secret `DISCORD_WEBHOOK` (même URL) dans **leur** dépôt.
