"""Écrans de liste : matières, emploi du temps, épreuves, travaux à rendre."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import modeles as m
from ..base import Base
from ..moteur.placement import minutes_preparation
from . import theme
from .theme import bouton_role, carte, en_tete, icone
from .commun import (
    JOURS,
    LIBELLES,
    tableau,
    texte_date,
    texte_date_heure,
    texte_duree,
    texte_heure,
)
from .formulaires import (
    FormulaireActivite,
    FormulaireAnnulation,
    FormulaireEpreuve,
    FormulaireMatiere,
    FormulaireTravail,
)


class PageListe(QWidget):
    """Tableau d'éléments avec les boutons Ajouter / Modifier / Supprimer."""

    donnees_modifiees = Signal()
    titre = ""
    aide = ""
    colonnes: list[str] = []
    message_suppression = "Supprimer « {} » ?"
    texte_vide = "Rien pour l'instant. Cliquez sur « Ajouter » pour commencer."

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(parent)
        self.base = base
        self.objets: list = []

        entete, self.actions = en_tete(self.titre, self.aide)
        self.bouton_ajouter = bouton_role(QPushButton(icone("ajouter", "#FFFFFF"), " Ajouter"), "primaire")
        self.bouton_modifier = QPushButton(icone("modifier"), " Modifier")
        self.bouton_supprimer = bouton_role(QPushButton(icone("supprimer", theme.DANGER), " Supprimer"), "danger")
        self.bouton_ajouter.clicked.connect(self.ajouter)
        self.bouton_modifier.clicked.connect(self.modifier)
        self.bouton_supprimer.clicked.connect(self.supprimer)
        for bouton in (self.bouton_supprimer, self.bouton_modifier, self.bouton_ajouter):
            self.actions.addWidget(bouton)

        self.table = tableau(self.colonnes)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.doubleClicked.connect(self.modifier)
        self.table.itemSelectionChanged.connect(self._actualiser_boutons)

        self.vide = QLabel(self.texte_vide)
        self.vide.setObjectName("vide")
        self.vide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vide.setWordWrap(True)
        self.cadre_vide = carte()
        disposition_vide = QVBoxLayout(self.cadre_vide)
        disposition_vide.addWidget(self.vide)

        disposition = QVBoxLayout(self)
        disposition.setContentsMargins(28, 24, 28, 20)
        disposition.setSpacing(16)
        disposition.addWidget(entete)
        disposition.addWidget(self.table, 1)
        disposition.addWidget(self.cadre_vide, 1)
        self.rafraichir()

    # À définir par chaque écran --------------------------------------------

    @property
    def depot(self):
        raise NotImplementedError

    def elements(self) -> list:
        return self.depot.lister()

    def ligne(self, objet) -> list[str]:
        raise NotImplementedError

    def formulaire(self, objet=None):
        raise NotImplementedError

    def nom(self, objet) -> str:
        return getattr(objet, "nom", None) or getattr(objet, "intitule", "") or "cet élément"

    def couleur(self, objet) -> str | None:
        return None

    def apres_enregistrement(self, formulaire, objet) -> None:
        """Pour enregistrer ce qui dépend de l'objet (ex. sous-tâches)."""

    # Mécanique commune ------------------------------------------------------

    def matieres(self) -> list[m.Matiere]:
        return self.base.matieres.lister(ordre="nom")

    def nom_matiere(self, matiere_id: int | None) -> str:
        if matiere_id is None:
            return ""
        matiere = self.base.matieres.obtenir(matiere_id)
        return matiere.nom if matiere else "?"

    def rafraichir(self) -> None:
        self.objets = self.elements()
        self.table.setRowCount(len(self.objets))
        for n, objet in enumerate(self.objets):
            couleur = self.couleur(objet)
            for c, texte in enumerate(self.ligne(objet)):
                cellule = QTableWidgetItem(texte)
                if c == 0 and couleur:
                    cellule.setData(Qt.ItemDataRole.DecorationRole, QColor(couleur))
                self.table.setItem(n, c, cellule)
        self.table.setVisible(bool(self.objets))
        self.cadre_vide.setVisible(not self.objets)
        self._actualiser_boutons()

    def _actualiser_boutons(self) -> None:
        choisi = self.selection() is not None
        self.bouton_modifier.setEnabled(choisi)
        self.bouton_supprimer.setEnabled(choisi)

    def selection(self):
        ligne = self.table.currentRow()
        return self.objets[ligne] if 0 <= ligne < len(self.objets) else None

    def _ouvrir(self, objet=None):
        try:
            return self.formulaire(objet)
        except ValueError as erreur:  # ex. aucune matière encore saisie
            QMessageBox.information(self, self.titre, str(erreur))
            return None

    def ajouter(self) -> None:
        formulaire = self._ouvrir()
        if formulaire and formulaire.exec():
            objet = self.depot.ajouter(formulaire.resultat)
            self.apres_enregistrement(formulaire, objet)
            self._modifie()

    def modifier(self) -> None:
        objet = self.selection()
        if objet is None:
            QMessageBox.information(self, self.titre, "Sélectionnez d'abord une ligne.")
            return
        formulaire = self._ouvrir(objet)
        if formulaire and formulaire.exec():
            self.depot.modifier(formulaire.resultat)
            self.apres_enregistrement(formulaire, formulaire.resultat)
            self._modifie()

    def supprimer(self) -> None:
        objet = self.selection()
        if objet is None:
            QMessageBox.information(self, self.titre, "Sélectionnez d'abord une ligne.")
            return
        reponse = QMessageBox.question(self, "Confirmer", self.message_suppression.format(self.nom(objet)))
        if reponse != QMessageBox.StandardButton.Yes:
            return
        try:
            self.depot.supprimer(objet.id)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self, "Suppression impossible",
                f"« {self.nom(objet)} » est encore utilisée par une épreuve ou un travail. "
                "Supprimez ou modifiez-les d'abord.",
            )
            return
        self._modifie()

    def _modifie(self) -> None:
        self.rafraichir()
        self.donnees_modifiees.emit()


class PageMatieres(PageListe):
    titre = "Matières"
    aide = (
        "La difficulté et la maîtrise (de 1 à 5) servent à répartir les révisions : "
        "une matière difficile et peu maîtrisée reçoit plus de temps."
    )
    colonnes = ["Matière", "Code", "Coefficient", "Difficulté", "Maîtrise", "État"]
    texte_vide = "Aucune matière pour l'instant.\nCommencez par ajouter vos matières : tout le reste s'y rattache."

    @property
    def depot(self):
        return self.base.matieres

    def elements(self):
        return self.base.matieres.lister(ordre="nom")

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(base, parent)
        # Remplaçables dans les tests (aucune fenêtre bloquante)
        self.choisir_suppression = self._demander_suppression

    def elements(self):
        # Les matières en cours d'abord, les terminées ensuite
        return sorted(self.base.matieres.lister(ordre="nom"), key=lambda x: x.terminee)

    def ligne(self, x: m.Matiere):
        etat = "Terminée — plus de révisions" if x.terminee else "En cours"
        return [x.nom, x.code, f"{x.coefficient:g}", f"{x.difficulte} / 5", f"{x.maitrise} / 5", etat]

    def couleur(self, x: m.Matiere):
        return "#C3C8D6" if x.terminee else x.couleur

    def formulaire(self, objet=None):
        return FormulaireMatiere(objet, self)

    # --- Suppression guidée ----------------------------------------------------

    def utilisations(self, matiere: m.Matiere) -> dict[str, int]:
        cle = ("matiere_id = ?", (matiere.id,))
        return {
            "épreuve(s)": len(self.base.epreuves.lister(*cle)),
            "travail(aux) à rendre": len(self.base.travaux.lister(*cle)),
            "cours / activité(s)": len(self.base.activites.lister(*cle)),
            "séance(s)": len(self.base.seances.lister(*cle)),
        }

    def supprimer(self) -> None:
        matiere = self.selection()
        if matiere is None:
            QMessageBox.information(self, self.titre, "Sélectionnez d'abord une ligne.")
            return
        usages = {k: v for k, v in self.utilisations(matiere).items() if v}
        if not usages:
            super().supprimer()
            return
        choix = self.choisir_suppression(matiere, usages)
        if choix == "terminer":
            self.marquer_terminee(matiere)
        elif choix == "tout":
            self.supprimer_avec_tout(matiere)

    def _demander_suppression(self, matiere: m.Matiere, usages: dict[str, int]) -> str | None:
        detail = ", ".join(f"{n} {nom}" for nom, n in usages.items())
        boite = QMessageBox(self)
        boite.setWindowTitle("Cette matière est encore utilisée")
        boite.setIcon(QMessageBox.Icon.Question)
        boite.setText(f"« {matiere.nom} » est liée à : {detail}.")
        boite.setInformativeText(
            "Si elle est finie, marquez-la « terminée » : le planning ne la proposera plus, "
            "et son historique (bilan, devoirs passés) est gardé.\n\n"
            "« Tout supprimer » efface aussi ses épreuves, travaux, cours et séances. C'est définitif."
        )
        terminer = boite.addButton("Marquer terminée", QMessageBox.ButtonRole.AcceptRole)
        tout = boite.addButton("Tout supprimer", QMessageBox.ButtonRole.DestructiveRole)
        boite.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        boite.setDefaultButton(terminer)
        boite.exec()
        if boite.clickedButton() is terminer:
            return "terminer"
        if boite.clickedButton() is tout:
            return "tout"
        return None

    def marquer_terminee(self, matiere: m.Matiere) -> None:
        matiere.terminee = True
        self.base.matieres.modifier(matiere)
        self._modifie()

    def supprimer_avec_tout(self, matiere: m.Matiere) -> None:
        cle = ("matiere_id = ?", (matiere.id,))
        for depot in (self.base.seances, self.base.epreuves, self.base.travaux, self.base.activites):
            for objet in depot.lister(*cle):
                depot.supprimer(objet.id)
        self.base.matieres.supprimer(matiere.id)
        self._modifie()


class PageEmploiDuTemps(PageListe):
    titre = "Emploi du temps"
    aide = (
        "Cours, TD, TP, trajets et engagements à heure fixe : le planning ne les déplace jamais. "
        "Pour un repos ou une indisponibilité (soirée, journée), choisissez le type « Personnel / repos »."
    )
    colonnes = ["Activité", "Type", "Quand", "Horaire", "Matière", "Annulations"]
    texte_vide = "Votre emploi du temps est vide.\nAjoutez vos cours, trajets et engagements à heure fixe."

    def __init__(self, base: Base, parent=None) -> None:
        super().__init__(base, parent)
        annuler = QPushButton(icone("annuler"), " Annuler une séance…")
        annuler.setToolTip("Jour férié, cours annulé : libère ce créneau pour une seule date")
        annuler.clicked.connect(self.annuler_une_seance)
        self.actions.insertWidget(0, annuler)

    @property
    def depot(self):
        return self.base.activites

    def elements(self):
        return self.base.activites.lister(ordre="jour_semaine IS NULL, jour_semaine, date, heure_debut")

    def ligne(self, x: m.ActiviteFixe):
        if x.recurrente:
            quand = f"Chaque {JOURS[x.jour_semaine].lower()}"
            if x.valide_du or x.valide_au:
                quand += " (période limitée)"
        else:
            quand = texte_date(x.date)
        horaire = f"{texte_heure(x.heure_debut)} – {texte_heure(x.heure_fin)}"
        if x.marge_avant_min or x.marge_apres_min:
            horaire += f" (+ trajet {x.marge_avant_min}/{x.marge_apres_min} min)"
        annulations = self.base.exceptions.lister("activite_id = ?", (x.id,), ordre="date")
        return [
            x.nom, LIBELLES[x.type], quand, horaire, self.nom_matiere(x.matiere_id),
            ", ".join(f"{e.date:%d/%m}" for e in annulations),
        ]

    def formulaire(self, objet=None):
        return FormulaireActivite(self.matieres(), objet, self)

    def annuler_une_seance(self) -> None:
        activite = self.selection()
        if activite is None or not activite.recurrente:
            QMessageBox.information(self, self.titre, "Sélectionnez d'abord une activité hebdomadaire.")
            return
        formulaire = FormulaireAnnulation(activite, self)
        if formulaire.exec():
            try:
                self.base.exceptions.ajouter(formulaire.resultat)
            except sqlite3.IntegrityError:
                QMessageBox.information(self, self.titre, "Cette séance est déjà annulée.")
                return
            self._modifie()


class PageEpreuves(PageListe):
    titre = "Épreuves"
    aide = (
        "Interrogations, devoirs surveillés, compositions et examens à date et heure fixes. "
        "Le planning prévoit leur préparation avant, jamais après."
    )
    colonnes = ["Épreuve", "Matière", "Date", "Horaire", "Préparation prévue", "État"]
    texte_vide = "Aucune épreuve programmée.\nAjoutez vos interrogations, devoirs et compositions dès que vous les connaissez."

    @property
    def depot(self):
        return self.base.epreuves

    def elements(self):
        return self.base.epreuves.lister(ordre="debut")

    def nom(self, x: m.Epreuve):
        return x.intitule or f"{LIBELLES[x.type]} de {self.nom_matiere(x.matiere_id)}"

    def ligne(self, x: m.Epreuve):
        temps = texte_duree(minutes_preparation(x))
        if x.minutes_preparation is None:
            temps += " (estimé)"
        return [
            x.intitule or LIBELLES[x.type], self.nom_matiere(x.matiere_id), texte_date(x.debut.date()),
            f"{x.debut:%H:%M} – {x.fin:%H:%M}", temps, LIBELLES[x.etat],
        ]

    def formulaire(self, objet=None):
        return FormulaireEpreuve(self.matieres(), objet, self)


class PageTravaux(PageListe):
    titre = "Travaux à rendre"
    aide = (
        "Exercices, TD, rapports, projets, exposés… Indiquez le temps estimé ; "
        "s'il est déjà commencé, seul le temps restant est planifié."
    )
    colonnes = ["Travail", "Matière", "À rendre le", "Reste à faire", "Étapes", "État"]
    texte_vide = "Aucun travail à rendre.\nAjoutez exercices, rapports, exposés… avec une estimation du temps."

    @property
    def depot(self):
        return self.base.travaux

    def elements(self):
        return self.base.travaux.lister(ordre="echeance")

    def sous_taches(self, travail_id: int | None) -> list[m.SousTache]:
        if travail_id is None:
            return []
        return self.base.sous_taches.lister("travail_id = ?", (travail_id,), ordre="ordre")

    def ligne(self, x: m.Travail):
        etapes = self.sous_taches(x.id)
        faites = sum(st.terminee for st in etapes)
        return [
            x.intitule, self.nom_matiere(x.matiere_id), texte_date_heure(x.echeance),
            f"{texte_duree(x.minutes_restantes)} sur {texte_duree(x.minutes_estimees)}",
            f"{faites} / {len(etapes)}" if etapes else "—", LIBELLES[x.etat],
        ]

    def formulaire(self, objet=None):
        return FormulaireTravail(self.matieres(), objet, self, self.sous_taches(objet.id if objet else None))

    def apres_enregistrement(self, formulaire, travail: m.Travail) -> None:
        for ancienne in self.sous_taches(travail.id):
            self.base.sous_taches.supprimer(ancienne.id)
        for etape in formulaire.etapes.valeurs(travail.id):
            self.base.sous_taches.ajouter(etape)
