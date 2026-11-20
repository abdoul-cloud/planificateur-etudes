"""Écran d'accueil : la journée, la semaine et les prochaines échéances."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import occurrences
from ..suivi import a_pointer, marquer
from . import theme
from .calendrier import MOIS, lundi_de
from .commun import JOURS, LIBELLES, texte_duree
from .theme import bouton_role, carte, icone, pixmap_icone, vider


def _texte_jour(jour: date) -> str:
    return f"{JOURS[jour.weekday()].lower()} {jour.day} {MOIS[jour.month - 1]}"


def _dans(delai: timedelta) -> str:
    jours = delai.days
    if jours <= 0:
        return "aujourd'hui"
    if jours == 1:
        return "demain"
    return f"dans {jours} jours"


class _Statistique(QWidget):
    def __init__(self, icone_nom: str, titre: str, parent=None) -> None:
        super().__init__(parent)
        self.cadre = carte()
        disposition = QHBoxLayout(self.cadre)
        disposition.setContentsMargins(16, 16, 16, 16)
        disposition.setSpacing(12)
        pastille = QLabel()
        pastille.setFixedSize(42, 42)
        pastille.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pastille.setStyleSheet(f"background: {theme.ACCENT_PALE}; border-radius: 21px;")
        pastille.setPixmap(pixmap_icone(icone_nom, theme.ACCENT, 20))
        textes = QVBoxLayout()
        textes.setSpacing(0)
        libelle = QLabel(titre)
        libelle.setObjectName("doux")
        self.valeur = QLabel("—")
        self.valeur.setObjectName("grandChiffre")
        self.detail = QLabel("")
        self.detail.setObjectName("pale")
        libelle.setWordWrap(True)
        self.detail.setWordWrap(True)
        for w in (libelle, self.valeur, self.detail):
            textes.addWidget(w)
        disposition.addWidget(pastille, 0, Qt.AlignmentFlag.AlignTop)
        disposition.addLayout(textes, 1)
        enveloppe = QVBoxLayout(self)
        enveloppe.setContentsMargins(0, 0, 0, 0)
        enveloppe.addWidget(self.cadre)

    def definir(self, valeur: str, detail: str = "") -> None:
        self.valeur.setText(valeur)
        self.detail.setText(detail)


class _Liste(QWidget):
    """Carte avec un titre et des lignes « pastille de couleur · texte · détail »."""

    def __init__(self, titre: str, vide: str, parent=None) -> None:
        super().__init__(parent)
        self.texte_vide = vide
        self.cadre = carte()
        self.lignes = QVBoxLayout(self.cadre)
        self.lignes.setContentsMargins(20, 16, 20, 16)
        self.lignes.setSpacing(10)
        entete = QLabel(titre)
        entete.setObjectName("titreCarte")
        self.lignes.addWidget(entete)
        self.contenu = QVBoxLayout()
        self.contenu.setSpacing(8)
        self.lignes.addLayout(self.contenu)
        self.lignes.addStretch()
        enveloppe = QVBoxLayout(self)
        enveloppe.setContentsMargins(0, 0, 0, 0)
        enveloppe.addWidget(self.cadre)

    def definir(self, elements: list[tuple[str, str, str, str]]) -> None:
        """elements : (couleur, titre, sous-titre, étiquette à droite)."""
        vider(self.contenu)
        if not elements:
            vide = QLabel(self.texte_vide)
            vide.setObjectName("pale")
            vide.setWordWrap(True)
            self.contenu.addWidget(vide)
            return
        for couleur, titre, sous_titre, etiquette in elements:
            ligne = QWidget()
            disposition = QHBoxLayout(ligne)
            disposition.setContentsMargins(0, 2, 0, 2)
            disposition.setSpacing(12)
            barre = QLabel()
            barre.setFixedSize(4, 34)
            barre.setStyleSheet(f"background: {couleur}; border-radius: 2px;")
            textes = QVBoxLayout()
            textes.setSpacing(0)
            principal = QLabel(titre)
            principal.setStyleSheet("font-weight: 600;")
            secondaire = QLabel(sous_titre)
            secondaire.setObjectName("doux")
            textes.addWidget(principal)
            textes.addWidget(secondaire)
            disposition.addWidget(barre)
            disposition.addLayout(textes, 1)
            if etiquette:
                droite = QLabel(etiquette)
                droite.setObjectName("pastilleDanger" if etiquette in ("aujourd'hui", "demain") else "pastille")
                disposition.addWidget(droite, 0, Qt.AlignmentFlag.AlignVCenter)
            self.contenu.addWidget(ligne)


class _APointer(QWidget):
    """Séances passées, pas encore pointées : faite, en partie ou manquée."""

    pointe = Signal(object, object)  # séance, statut

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cadre = carte()
        colonne = QVBoxLayout(self.cadre)
        colonne.setContentsMargins(20, 16, 20, 16)
        colonne.setSpacing(10)
        entete = QHBoxLayout()
        titre = QLabel("À pointer")
        titre.setObjectName("titreCarte")
        self.compte = QLabel()
        self.compte.setObjectName("pastille")
        entete.addWidget(titre)
        entete.addWidget(self.compte)
        entete.addStretch()
        aide = QLabel("Ces séances sont passées : dites ce que vous avez réellement fait. "
                      "Une séance manquée est aussitôt replanifiée.")
        aide.setObjectName("doux")
        aide.setWordWrap(True)
        colonne.addLayout(entete)
        colonne.addWidget(aide)
        self.contenu = QVBoxLayout()
        self.contenu.setSpacing(6)
        colonne.addLayout(self.contenu)
        enveloppe = QVBoxLayout(self)
        enveloppe.setContentsMargins(0, 0, 0, 0)
        enveloppe.addWidget(self.cadre)

    def definir(self, seances: list[m.Seance], matieres: dict[int, m.Matiere]) -> None:
        vider(self.contenu)
        self.compte.setText(str(len(seances)))
        for s in seances[:5]:
            matiere = matieres.get(s.matiere_id)
            ligne = QWidget()
            disposition = QHBoxLayout(ligne)
            disposition.setContentsMargins(0, 2, 0, 2)
            disposition.setSpacing(10)
            barre = QLabel()
            barre.setFixedSize(4, 34)
            barre.setStyleSheet(f"background: {matiere.couleur if matiere else theme.ACCENT}; border-radius: 2px;")
            textes = QVBoxLayout()
            textes.setSpacing(0)
            principal = QLabel(f"{matiere.nom if matiere else 'Séance'} · {LIBELLES[s.type]}")
            principal.setStyleSheet("font-weight: 600;")
            secondaire = QLabel(f"{_texte_jour(s.debut.date())}, {s.debut:%H:%M} – {s.fin:%H:%M}")
            secondaire.setObjectName("doux")
            textes.addWidget(principal)
            textes.addWidget(secondaire)
            disposition.addWidget(barre)
            disposition.addLayout(textes, 1)
            for texte, statut, role in (("✓  Faite", m.StatutSeance.TERMINEE, "primaire"),
                                        ("½  En partie", m.StatutSeance.PARTIELLE, ""),
                                        ("✗  Manquée", m.StatutSeance.MANQUEE, "danger")):
                bouton = QPushButton(texte)
                if role:
                    bouton_role(bouton, role)
                bouton.clicked.connect(lambda _=False, s=s, st=statut: self.pointe.emit(s, st))
                disposition.addWidget(bouton)
            self.contenu.addWidget(ligne)
        if len(seances) > 5:
            reste = QLabel(f"… et {len(seances) - 5} autre{'s' if len(seances) > 6 else ''}, à pointer aussi depuis le planning (clic droit).")
            reste.setObjectName("pale")
            self.contenu.addWidget(reste)


class _BandeauVersion(QFrame):
    """« Version x.y.z disponible » : télécharger, ou ne plus la proposer."""

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.version = None
        self.setObjectName("bandeauVersion")
        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(18, 12, 12, 12)
        ligne.setSpacing(12)
        pictogramme = QLabel()
        pictogramme.setPixmap(pixmap_icone("restaurer", theme.ACCENT, 20))
        self.texte = QLabel()
        self.texte.setWordWrap(True)
        self.texte.setTextFormat(Qt.TextFormat.RichText)
        telecharger = bouton_role(QPushButton(icone("telecharger", "#FFFFFF"), " Télécharger"), "primaire")
        telecharger.setToolTip("Ouvre le téléchargement dans votre navigateur ; lancez ensuite le fichier : "
                               "vos données sont conservées.")
        telecharger.clicked.connect(self.telecharger)
        plus_tard = bouton_role(QPushButton("Plus tard"), "discret")
        plus_tard.setToolTip("Masquer jusqu'au prochain démarrage")
        plus_tard.clicked.connect(self.hide)
        ignorer = bouton_role(QPushButton("Ignorer cette version"), "discret")
        ignorer.clicked.connect(self.ignorer)
        ligne.addWidget(pictogramme)
        ligne.addWidget(self.texte, 1)
        for b in (ignorer, plus_tard, telecharger):
            ligne.addWidget(b)
        self.hide()

    def montrer(self, version) -> None:
        from .. import __version__

        self.version = version
        self.texte.setText(f"<b>Nouvelle version {version.numero} disponible</b> "
                           f"<span style='color:{theme.TEXTE_DOUX}'>(vous avez la {__version__}). "
                           f"<a href='{version.page}'>Voir les nouveautés</a></span>")
        self.texte.setOpenExternalLinks(True)
        self.show()

    def telecharger(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if self.version is not None:
            QDesktopServices.openUrl(QUrl(self.version.telechargement))

    def ignorer(self) -> None:
        from ..mises_a_jour import ignorer

        if self.version is not None:
            ignorer(self.base, self.version.numero)
        self.hide()


class _BandeauSeance(QFrame):
    """« Prochaine séance : Maths, 20:00 – 21:30 » avec le bouton Commencer (minuteur)."""

    commencer = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.seance = None
        self.setObjectName("bandeauSeance")
        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(18, 10, 12, 10)
        ligne.setSpacing(12)
        pictogramme = QLabel()
        pictogramme.setPixmap(pixmap_icone("horloge", theme.ACCENT, 20))
        self.texte = QLabel()
        self.texte.setWordWrap(True)
        self.bouton = bouton_role(QPushButton(icone("generer", "#FFFFFF"), " Commencer"), "primaire")
        self.bouton.setToolTip("Lance le minuteur : pauses proposées, et la séance se pointe toute seule à la fin")
        self.bouton.clicked.connect(lambda: self.seance is not None and self.commencer.emit(self.seance))
        ligne.addWidget(pictogramme)
        ligne.addWidget(self.texte, 1)
        ligne.addWidget(self.bouton)
        self.hide()

    def definir(self, seance, nom: str, maintenant, en_cours: bool) -> None:
        self.seance = seance
        if seance is None:
            self.hide()
            return
        if en_cours:
            self.texte.setText(f"<b>Séance en cours dans le minuteur</b> · {nom}")
            self.bouton.setText(" Afficher")
        else:
            quand = ("maintenant" if seance.debut <= maintenant
                     else f"dans {texte_duree(int((seance.debut - maintenant).total_seconds() // 60))}")
            self.texte.setText(f"<b>{nom}</b> · {seance.debut:%H:%M} – {seance.fin:%H:%M} "
                               f"<span style='color:{theme.TEXTE_DOUX}'>({quand})</span>")
            self.bouton.setText(" Commencer")
        self.show()


class PageAccueil(QWidget):
    aller_a = Signal(str)
    commencer = Signal(object)
    donnees_modifiees = Signal()
    replanifier = Signal()

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.maintenant: datetime | None = None  # pour les tests

        self.salut = QLabel()
        self.salut.setObjectName("titrePage")
        self.date_du_jour = QLabel()
        self.date_du_jour.setObjectName("sousTitre")
        bouton_planning = bouton_role(QPushButton(icone("planning", "#FFFFFF"), " Ouvrir le planning"), "primaire")
        bouton_planning.clicked.connect(lambda: self.aller_a.emit("Planning"))
        haut = QHBoxLayout()
        textes = QVBoxLayout()
        textes.setSpacing(2)
        textes.addWidget(self.salut)
        textes.addWidget(self.date_du_jour)
        haut.addLayout(textes, 1)
        haut.addWidget(bouton_planning, 0, Qt.AlignmentFlag.AlignTop)
        self.bandeau_version = _BandeauVersion(base)
        self.bandeau_seance = _BandeauSeance()
        self.bandeau_seance.commencer.connect(self.commencer)
        self.minuteur_actif = lambda: None  # fourni par la fenêtre : id de la séance chronométrée, ou None

        self.stat_jour = _Statistique("horloge", "Aujourd'hui")
        self.stat_semaine = _Statistique("planning", "Cette semaine")
        self.stat_epreuve = _Statistique("epreuves", "Prochaine épreuve")
        self.stat_travaux = _Statistique("travaux", "À rendre sous 7 jours")
        # 4 cartes côte à côte, ou 2 × 2 dans une fenêtre étroite (voir resizeEvent)
        statistiques = QGridLayout()
        statistiques.setSpacing(16)
        self._statistiques = statistiques
        self._colonnes_stats = 0
        self._placer_statistiques(4)

        self.a_pointer = _APointer()
        self.a_pointer.pointe.connect(self._pointer_depuis_bouton)

        self.liste_jour = _Liste("Programme du jour", "Rien de prévu aujourd'hui. Profitez-en, ou générez le planning.")
        self.liste_echeances = _Liste("Prochaines échéances", "Aucune épreuve ni travail à rendre dans les deux semaines.")
        colonnes = QGridLayout()
        colonnes.setSpacing(16)
        colonnes.addWidget(self.liste_jour, 0, 0)
        colonnes.addWidget(self.liste_echeances, 0, 1)

        # Premiers pas, quand rien n'est saisi
        self.premiers_pas = carte()
        pas = QVBoxLayout(self.premiers_pas)
        pas.setContentsMargins(24, 20, 24, 20)
        pas.setSpacing(10)
        titre_pas = QLabel("Bienvenue ! Trois étapes pour obtenir votre premier planning")
        titre_pas.setObjectName("titreCarte")
        titre_pas.setWordWrap(True)
        pas.addWidget(titre_pas)
        for numero, (texte, ecran) in enumerate(
            [("Ajoutez vos matières", "Matières"), ("Saisissez votre emploi du temps", "Emploi du temps"),
             ("Ajoutez épreuves et travaux, puis générez le planning", "Épreuves")], start=1
        ):
            ligne = QHBoxLayout()
            rond = QLabel(str(numero))
            rond.setFixedSize(28, 28)
            rond.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rond.setStyleSheet(f"background: {theme.ACCENT}; color: white; border-radius: 14px; font-weight: 600;")
            libelle = QLabel(texte)
            aller = QPushButton("Commencer" if numero == 1 else "Ouvrir")
            aller.clicked.connect(lambda _=False, e=ecran: self.aller_a.emit(e))
            ligne.addWidget(rond)
            ligne.addWidget(libelle, 1)
            ligne.addWidget(aller)
            pas.addLayout(ligne)

        contenu = QWidget()
        contenu.setObjectName("defile")
        defilement = QScrollArea()
        defilement.setWidgetResizable(True)
        defilement.setFrameShape(QFrame.Shape.NoFrame)
        defilement.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        defilement.setWidget(contenu)
        enveloppe = QVBoxLayout(self)
        enveloppe.setContentsMargins(0, 0, 0, 0)
        enveloppe.addWidget(defilement)
        disposition = QVBoxLayout(contenu)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(18)
        disposition.addLayout(haut)
        disposition.addWidget(self.bandeau_version)
        disposition.addWidget(self.bandeau_seance)
        disposition.addWidget(self.premiers_pas)
        disposition.addLayout(statistiques)
        disposition.addWidget(self.a_pointer)
        disposition.addLayout(colonnes)
        disposition.addStretch(1)
        self.rafraichir()

    LARGEUR_QUATRE_STATS = 940

    def _placer_statistiques(self, colonnes: int) -> None:
        if colonnes == self._colonnes_stats:
            return
        self._colonnes_stats = colonnes
        cartes = (self.stat_jour, self.stat_semaine, self.stat_epreuve, self.stat_travaux)
        for s in cartes:
            self._statistiques.removeWidget(s)
        for n, s in enumerate(cartes):
            self._statistiques.addWidget(s, n // colonnes, n % colonnes)
        for c in range(4):
            self._statistiques.setColumnStretch(c, 1 if c < colonnes else 0)

    def resizeEvent(self, evenement) -> None:
        super().resizeEvent(evenement)
        self._placer_statistiques(4 if self.width() >= self.LARGEUR_QUATRE_STATS else 2)

    def _pointer_depuis_bouton(self, seance: m.Seance, statut: m.StatutSeance) -> None:
        minutes = None
        if statut is m.StatutSeance.PARTIELLE:
            minutes, ok = QInputDialog.getInt(
                self, "Faite en partie", "Minutes réellement travaillées :",
                max(5, seance.minutes // 2), 5, max(5, seance.minutes - 5), 5,
            )
            if not ok:
                return
        self.pointer(seance, statut, minutes)

    def pointer(self, seance: m.Seance, statut: m.StatutSeance, minutes: int | None = None) -> None:
        marquer(self.base, seance, statut, minutes)
        if statut is m.StatutSeance.MANQUEE:
            self.replanifier.emit()
        self.donnees_modifiees.emit()
        self.rafraichir()

    def rafraichir(self) -> None:
        maintenant = self.maintenant or datetime.now()
        aujourd_hui = maintenant.date()
        heure = maintenant.hour
        self.salut.setText("Bonsoir" if heure >= 18 else "Bonjour")
        self.date_du_jour.setText(_texte_jour(aujourd_hui).capitalize())
        matieres = {x.id: x for x in self.base.matieres.lister()}
        self.premiers_pas.setVisible(not matieres or not self.base.activites.lister())
        # Séance à lancer avec le minuteur (ou celle en cours dans le minuteur)
        from ..minuteur import seance_a_lancer

        chronometree = self.minuteur_actif()
        seance = self.base.seances.obtenir(chronometree) if chronometree else seance_a_lancer(self.base, maintenant)
        matiere = matieres.get(seance.matiere_id) if seance is not None else None
        self.bandeau_seance.definir(seance, matiere.nom if matiere else "Séance de travail", maintenant,
                                    en_cours=bool(chronometree))
        en_attente = a_pointer(self.base, maintenant)
        self.a_pointer.setVisible(bool(en_attente))
        self.a_pointer.definir(en_attente, matieres)

        def seances_entre(debut: date, fin: date) -> list[m.Seance]:
            return [
                s for s in self.base.seances.lister(
                    "debut >= ? AND debut < ?",
                    (datetime.combine(debut, time.min).isoformat(timespec="minutes"),
                     datetime.combine(fin, time.min).isoformat(timespec="minutes")),
                    ordre="debut",
                )
                if s.statut not in (m.StatutSeance.MANQUEE, m.StatutSeance.REPORTEE)
            ]

        du_jour = seances_entre(aujourd_hui, aujourd_hui + timedelta(days=1))
        restantes = [s for s in du_jour if s.fin > maintenant]
        self.stat_jour.definir(
            texte_duree(sum(s.minutes for s in du_jour)) if du_jour else "Libre",
            f"{len(restantes)} séance{'s' if len(restantes) > 1 else ''} à venir" if du_jour else "aucune séance prévue",
        )
        lundi = lundi_de(aujourd_hui)
        semaine = seances_entre(lundi, lundi + timedelta(days=7))
        self.stat_semaine.definir(texte_duree(sum(s.minutes for s in semaine)) if semaine else "0 h",
                                  f"{len(semaine)} séances planifiées")

        epreuves = [e for e in self.base.epreuves.lister(ordre="debut") if e.debut >= maintenant]
        if epreuves:
            e = epreuves[0]
            nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else ""
            self.stat_epreuve.definir(_dans(e.debut.date() - aujourd_hui).capitalize(), f"{LIBELLES[e.type]} de {nom}")
        else:
            self.stat_epreuve.definir("Aucune", "rien de programmé")
        bientot = [
            t for t in self.base.travaux.lister(ordre="echeance")
            if t.etat not in (m.EtatTravail.TERMINE, m.EtatTravail.RENDU)
            and maintenant <= t.echeance <= maintenant + timedelta(days=7)
        ]
        self.stat_travaux.definir(str(len(bientot)), f"{texte_duree(sum(t.minutes_restantes for t in bientot))} de travail restant" if bientot else "rien d'urgent")

        # Programme du jour : cours et séances mêlés, dans l'ordre
        programme = []
        for activite, horaire in occurrences(self.base.activites.lister(), aujourd_hui, aujourd_hui, self.base.exceptions.lister()):
            programme.append((horaire.debut, "#9AA1B5", activite.nom, f"{horaire.debut:%H:%M} – {horaire.fin:%H:%M} · {LIBELLES[activite.type]}", ""))
        for e in epreuves:
            if e.debut.date() == aujourd_hui:
                nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else ""
                programme.append((e.debut, theme.DANGER, f"⚑ {LIBELLES[e.type]} de {nom}", f"{e.debut:%H:%M} – {e.fin:%H:%M}", ""))
        for s in du_jour:
            matiere = matieres.get(s.matiere_id)
            etiquette = {m.StatutSeance.TERMINEE: "✓ faite", m.StatutSeance.PARTIELLE: "½ en partie",
                         m.StatutSeance.MANQUEE: "✗ manquée"}.get(s.statut, "")
            programme.append((s.debut, matiere.couleur if matiere else theme.ACCENT, matiere.nom if matiere else "Séance",
                              f"{s.debut:%H:%M} – {s.fin:%H:%M} · {LIBELLES[s.type]}", etiquette))
        programme.sort(key=lambda x: x[0])
        self.liste_jour.definir([x[1:] for x in programme])

        # Échéances des deux prochaines semaines
        echeances = []
        limite = maintenant + timedelta(days=14)
        for e in epreuves:
            if e.debut <= limite:
                nom = matieres[e.matiere_id].nom if e.matiere_id in matieres else ""
                echeances.append((e.debut, theme.DANGER, f"{LIBELLES[e.type]} de {nom}",
                                  f"{_texte_jour(e.debut.date())} à {e.debut:%H:%M}", _dans(e.debut.date() - aujourd_hui)))
        for t in self.base.travaux.lister(ordre="echeance"):
            if t.etat not in (m.EtatTravail.TERMINE, m.EtatTravail.RENDU) and maintenant <= t.echeance <= limite:
                matiere = matieres.get(t.matiere_id)
                echeances.append((t.echeance, matiere.couleur if matiere else theme.ACCENT, t.intitule,
                                  f"à rendre {_texte_jour(t.echeance.date())} · reste {texte_duree(t.minutes_restantes)}",
                                  _dans(t.echeance.date() - aujourd_hui)))
        echeances.sort(key=lambda x: x[0])
        self.liste_echeances.definir([x[1:] for x in echeances[:6]])
