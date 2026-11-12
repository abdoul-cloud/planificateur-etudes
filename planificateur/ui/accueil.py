"""Écran d'accueil : la journée, la semaine et les prochaines échéances."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import modeles as m
from ..base import Base
from ..moteur.creneaux import occurrences
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
        disposition.setContentsMargins(18, 16, 18, 16)
        disposition.setSpacing(14)
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


class PageAccueil(QWidget):
    aller_a = Signal(str)

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

        self.stat_jour = _Statistique("horloge", "Aujourd'hui")
        self.stat_semaine = _Statistique("planning", "Cette semaine")
        self.stat_epreuve = _Statistique("epreuves", "Prochaine épreuve")
        self.stat_travaux = _Statistique("travaux", "À rendre sous 7 jours")
        statistiques = QHBoxLayout()
        statistiques.setSpacing(16)
        for s in (self.stat_jour, self.stat_semaine, self.stat_epreuve, self.stat_travaux):
            statistiques.addWidget(s, 1)

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

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(18)
        disposition.addLayout(haut)
        disposition.addWidget(self.premiers_pas)
        disposition.addLayout(statistiques)
        disposition.addLayout(colonnes)
        disposition.addStretch(1)
        self.rafraichir()

    def rafraichir(self) -> None:
        maintenant = self.maintenant or datetime.now()
        aujourd_hui = maintenant.date()
        heure = maintenant.hour
        self.salut.setText("Bonsoir" if heure >= 18 else "Bonjour")
        self.date_du_jour.setText(_texte_jour(aujourd_hui).capitalize())
        matieres = {x.id: x for x in self.base.matieres.lister()}
        self.premiers_pas.setVisible(not matieres or not self.base.activites.lister())

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
            programme.append((s.debut, matiere.couleur if matiere else theme.ACCENT, matiere.nom if matiere else "Séance",
                              f"{s.debut:%H:%M} – {s.fin:%H:%M} · {LIBELLES[s.type]}",
                              "✓ fait" if s.statut is m.StatutSeance.TERMINEE else ""))
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
