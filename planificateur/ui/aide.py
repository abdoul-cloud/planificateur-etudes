"""Guide intégré : comment utiliser le planificateur, en quelques minutes de lecture."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import theme
from .theme import carte, en_tete, icone

SECTIONS = [
    ("premiers-pas", "Premiers pas", """
<ol>
<li><b>Matières</b> : ajoutez vos matières avec leur coefficient, la difficulté ressentie et votre maîtrise
(de 1 à 5). Une matière difficile et peu maîtrisée reçoit plus de temps.</li>
<li><b>Emploi du temps</b> : cliquez-glissez sur la grille pour ajouter un cours ; « copier sur d'autres jours »
fait gagner du temps. Avec l'assistant IA, vous pouvez aussi importer une photo ou un PDF.</li>
<li><b>Épreuves</b> et <b>Travaux à rendre</b> : ajoutez ce qui arrive, dès que vous le connaissez.</li>
<li><b>Planning</b> : cliquez sur <b>Générer le planning</b> (Ctrl+G).</li>
</ol>
<p>Les <b>Préférences</b> règlent votre rythme : heures de lever et de coucher, repas, durée des séances,
soirées de travail garanties, moments à éviter…</p>"""),
    ("planning", "Comment le planning est calculé", """
<ul>
<li>Les cours et les épreuves ne bougent jamais ; vos révisions se placent autour.</li>
<li>Les échéances les plus proches passent d'abord, étalées sur plusieurs jours plutôt qu'entassées la veille.</li>
<li>Aucune séance dans les heures qui précèdent une épreuve, ni après elle le même jour.</li>
<li>Les <b>plages garanties</b> (par défaut 20 h – 23 h du lundi au vendredi) sont toujours remplies ;
les autres moments libres reçoivent des séances espacées.</li>
<li>Un cours se révise de préférence la veille, sinon l'avant-veille.</li>
<li>Si tout ne tient pas, l'application le dit (<i>Bilan › Reste à placer</i>) au lieu de surcharger vos journées.</li>
</ul>
<p>Vous pouvez déplacer une séance à la souris : elle est alors verrouillée et ne bougera plus au prochain calcul.</p>"""),
    ("suivi", "Pointer ses séances et le minuteur", """
<p>Après chaque séance, pointez-la : <b>faite</b>, <b>faite en partie</b> ou <b>manquée</b> (clic droit sur la
séance dans le Planning, ou depuis l'Accueil). Une séance manquée est aussitôt replanifiée.</p>
<p>Plus simple encore : le <b>minuteur</b>. Cliquez sur <b>Commencer</b> dans le bandeau de l'Accueil
(ou Ctrl+M). Une petite fenêtre compte le temps, propose une pause toutes les 25 minutes, et pointe la séance
toute seule quand vous cliquez sur <b>Terminer</b>.</p>
<p>Le <b>Bilan</b> compare ce qui était prévu et ce qui a été fait. Après quelques séances pointées, il donne
des <b>conseils</b> (créneau souvent manqué, séances trop longues…) applicables d'un clic.</p>"""),
    ("assistant", "L'assistant IA (facultatif)", """
<p>Avec votre propre clé Gemini gratuite (<i>Préférences › Assistant IA</i>), vous pouvez demander en langage
naturel : « J'ai un DS de réseaux samedi de 14 h à 17 h », « Je ne peux pas travailler ce soir »,
« Explique-moi la transformée de Fourier », « Fais-moi un quiz sur le chapitre 3 »…</p>
<ul>
<li>L'assistant <b>propose</b>, vous <b>décidez</b> : rien n'est modifié sans un clic sur <b>Appliquer</b>.</li>
<li>Joignez une photo ou un PDF de votre <b>emploi du temps</b> ou de votre <b>calendrier d'examens</b> :
il le lit, vous vérifiez chaque ligne avant l'ajout.</li>
<li>Vos conversations sont gardées dans l'<b>historique</b> (à gauche), sur cet ordinateur uniquement.
Clic droit pour renommer ou supprimer.</li>
<li>Seuls votre message, les données utiles du planificateur et le fichier joint sont envoyés à Google ;
<i>Voir ce qui est envoyé</i> montre le dernier échange.</li>
</ul>"""),
    ("rappels", "Rappels et notifications", """
<p>Notification Windows avant chaque séance, la veille d'une épreuve, avant un travail à rendre et pour le point
du soir (<i>Préférences › Rappels et notifications</i>). Pour les recevoir, l'application reste discrètement près
de l'horloge quand vous fermez la fenêtre : clic droit sur son icône pour la quitter. Elle peut aussi démarrer
avec Windows.</p>"""),
    ("agenda", "Agenda, impression et export", """
<ul>
<li><i>Planning › Exporter</i> : PDF à imprimer, image, ou <b>agenda .ics</b> à importer dans Google Agenda
(<i>Paramètres › Importer et exporter</i>) ou Outlook, pour tout retrouver sur votre téléphone.</li>
<li><i>Épreuves › Imprimer</i> : la liste des épreuves à venir, classée par mois.</li>
</ul>"""),
    ("sauvegardes", "Sauvegardes", """
<p>Une copie est faite chaque jour sur cet ordinateur. Pour vous protéger d'une panne, choisissez aussi une
<b>copie automatique ailleurs</b> (<i>Sauvegarde</i>) : clé USB, disque externe ou OneDrive. En cas de problème,
<i>Sauvegarde › Restaurer</i> remet vos données, après vérification du fichier.</p>
<p>Les mises à jour ne touchent jamais vos données : il suffit d'installer la nouvelle version par-dessus.</p>"""),
    ("raccourcis", "Raccourcis clavier", """
<table cellspacing='0' cellpadding='4'>
<tr><td><b>Ctrl+1 … Ctrl+0</b></td><td>Aller à un écran (dans l'ordre du menu)</td></tr>
<tr><td><b>Ctrl+G</b></td><td>Générer le planning</td></tr>
<tr><td><b>Ctrl+N</b></td><td>Ajouter (matière, épreuve, travail : selon l'écran)</td></tr>
<tr><td><b>Ctrl+← / Ctrl+→</b></td><td>Semaine précédente / suivante</td></tr>
<tr><td><b>Ctrl+T</b></td><td>Revenir à cette semaine</td></tr>
<tr><td><b>Ctrl+P</b></td><td>Imprimer (planning, ou liste des épreuves)</td></tr>
<tr><td><b>Ctrl+M</b></td><td>Commencer la séance du moment (minuteur)</td></tr>
<tr><td><b>Ctrl+Entrée</b></td><td>Envoyer un message à l'assistant</td></tr>
<tr><td><b>F1</b></td><td>Ouvrir ce guide</td></tr>
</table>"""),
    ("confidentialite", "Vos données", """
<p>Tout reste sur votre ordinateur, dans un seul fichier (<i>Sauvegarde › Fichier de données</i>). Internet
n'est utilisé que pour l'assistant IA (si vous ajoutez une clé) et pour savoir, une fois par jour, si une nouvelle
version existe (désactivable dans <i>Préférences › Nouvelles versions</i>). Aucune donnée personnelle n'est
envoyée pour cette vérification.</p>
<p>Un problème, une idée ? Cliquez sur <b>Signaler un problème</b> en bas du menu.</p>"""),
]


def html_du_guide() -> str:
    sommaire = " · ".join(f"<a href='#{ancre}'>{titre}</a>" for ancre, titre, _ in SECTIONS)
    corps = "".join(f"<h2><a name='{ancre}'></a>{titre}</h2>{contenu}" for ancre, titre, contenu in SECTIONS)
    return f"""
    <style>
      body {{ font-family: 'Segoe UI'; font-size: 10.5pt; color: {theme.TEXTE}; }}
      h2 {{ font-size: 13pt; color: {theme.ACCENT}; margin-top: 22px; margin-bottom: 6px; }}
      a {{ color: {theme.ACCENT}; text-decoration: none; }}
      li {{ margin-bottom: 4px; }}
      p {{ margin-top: 4px; margin-bottom: 8px; }}
    </style>
    <p style='color:{theme.TEXTE_DOUX}'>{sommaire}</p>{corps}"""


class PageAide(QWidget):
    aller_a = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        entete, actions = en_tete("Aide et guide", "Tout ce qu'il faut savoir pour bien utiliser le planificateur.")
        retour = QPushButton(icone("accueil"), " Retour à l'accueil")
        retour.clicked.connect(lambda: self.aller_a.emit("Accueil"))
        actions.addWidget(retour)
        self.texte = QTextBrowser()
        self.texte.setObjectName("guide")
        self.texte.setStyleSheet("QTextBrowser#guide { border: none; background: transparent; }")
        self.texte.setOpenExternalLinks(False)
        self.texte.setHtml(html_du_guide())
        self.texte.anchorClicked.connect(lambda url: self.texte.scrollToAnchor(url.fragment()))
        cadre = carte()
        interieur = QHBoxLayout(cadre)
        interieur.setContentsMargins(24, 16, 16, 16)
        interieur.addWidget(self.texte)
        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(16)
        disposition.addWidget(entete)
        disposition.addWidget(cadre, 1)

    def aller_a_section(self, ancre: str) -> None:
        self.texte.scrollToAnchor(ancre)

