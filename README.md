# Planificateur d'études

Application de bureau personnelle, entièrement hors ligne, qui transforme un emploi du temps, des épreuves et des travaux à rendre en un planning de travail hebdomadaire réaliste.

## Lancer l'application

Double-cliquer sur **`Lancer.bat`**, ou :

```bash
.venv/Scripts/python.exe -m planificateur
```

Les données sont enregistrées dans `%APPDATA%\PlanificateurEtudes\donnees.db`. Une copie automatique est faite chaque jour dans le sous-dossier `sauvegardes` (les 10 dernières sont gardées).

## Installer sur une autre machine

Il faut Python 3.12 ou plus récent. Depuis ce dossier :

```bash
py -3.12 -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -e .[dev]
```

## Installateur Windows

Le fichier `build\installateur\Installer-PlanificateurEtudes-0.2.0.exe` installe l'application sans droits administrateur : raccourci dans le menu Démarrer (et sur le Bureau si on le coche), désinstallation depuis Paramètres > Applications. Il n'a besoin ni de Python ni d'Internet. Les données de `%APPDATA%\PlanificateurEtudes` ne sont jamais supprimées, ni par une mise à jour ni par une désinstallation.

Pour le reconstruire (tests, application autonome, auto-test de l'exécutable, puis installateur) :

```bash
powershell -ExecutionPolicy Bypass -File packaging/construire.ps1
```

Outils nécessaires : `pip install -e .[dev]` (PyInstaller, Pillow, pytest) et Inno Setup 6 (`winget install JRSoftware.InnoSetup`). Pour une nouvelle version, changer le numéro dans `pyproject.toml`, `planificateur/__main__.py`, `packaging/version.txt` et `packaging/installateur.iss`.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

## Organisation

| Dossier / fichier | Rôle |
|---|---|
| `planificateur/modeles.py` | Données : matières, activités fixes, épreuves, travaux, séances, préférences |
| `planificateur/base.py` | Stockage SQLite, migrations, sauvegarde et restauration vérifiées |
| `planificateur/moteur/` | Moteur de planification, indépendant de l'interface : créneaux libres et placement |
| `planificateur/suivi.py` | Pointage des séances, temps restant, bilan |
| `planificateur/ui/` | Interface PySide6 : accueil, planning, bilan, saisies, préférences, sauvegarde, export |
| `tests/` | Tests du moteur, des scénarios du cahier des charges et de l'interface |

## Règles de planification

- Les cours, activités fixes et épreuves ne sont jamais déplacés.
- Les échéances les plus proches sont servies d'abord, avec au plus un passage par jour pour une même épreuve ou un même travail, dans les plages préférées si possible.
- Aucune séance pendant les pauses et repas, ni dans les 3 h avant une épreuve ; 2 h au plus le jour d'une épreuve ; le jour le moins chargé est choisi à préférence égale.
- Les révisions régulières viennent ensuite, dans la limite d'un budget hebdomadaire, réparties selon coefficient × difficulté × (6 − maîtrise).
- Ce qui ne tient pas est signalé avec le temps manquant, sans surcharger les journées.
- Les séances faites, déplacées à la main ou verrouillées ne sont jamais modifiées par un recalcul.

Tous ces réglages se changent dans l'écran Préférences.
