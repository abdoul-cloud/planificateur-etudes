# Mentions légales et composants tiers

Le Planificateur d'études est distribué sous licence MIT (voir `LICENSE`). L'application installée contient ou utilise les composants suivants, chacun sous sa propre licence.

| Composant | Rôle | Licence | Code source |
|---|---|---|---|
| Python 3.12 | Langage et bibliothèque standard, embarqués dans l'application | Python Software Foundation License | https://www.python.org/downloads/source/ |
| Qt 6 et PySide6 (Qt for Python) | Interface graphique | GNU LGPL v3 | https://code.qt.io/ et https://download.qt.io/official_releases/QtForPython/ |
| PyInstaller (programme de lancement) | Transforme l'application en exécutable autonome | GPL v2 avec exception autorisant la diffusion d'applications | https://github.com/pyinstaller/pyinstaller |
| Inno Setup | Programme d'installation | Licence Inno Setup (utilisation gratuite) | https://jrsoftware.org/isinfo.php |

## À propos de Qt / PySide6 (LGPL v3)

Qt et PySide6 sont fournis sous forme de bibliothèques séparées (fichiers `.dll` et `.pyd` du dossier `_internal` de l'application installée), sans modification. Conformément à la LGPL v3, vous pouvez les remplacer par une autre version compatible. Le texte de la licence est disponible sur https://www.gnu.org/licenses/lgpl-3.0.html, et le code source correspondant aux adresses ci-dessus.

## Icônes et polices

Les icônes de l'interface sont dessinées à partir des polices d'icônes de Windows (Segoe Fluent Icons ou Segoe MDL2 Assets) déjà présentes sur l'ordinateur : elles ne sont pas distribuées avec l'application. L'icône de l'application est un dessin original du projet.

## Service Gemini (facultatif)

L'assistant IA utilise l'API Gemini de Google avec la clé personnelle de chaque utilisateur, qui accepte pour cela les conditions de Google (https://ai.google.dev/gemini-api/terms). Sans clé, aucune donnée n'est envoyée.
