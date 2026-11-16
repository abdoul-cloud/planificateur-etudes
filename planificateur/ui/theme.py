"""Identité visuelle : couleurs, icônes et feuille de style de l'application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

IMAGES = (Path(__file__).with_name("images")).as_posix()

# --- Couleurs ----------------------------------------------------------------

FOND = "#F4F5FA"
SURFACE = "#FFFFFF"
BORDURE = "#E4E7EF"
BORDURE_CHAMP = "#D5D9E4"
TEXTE = "#1F2433"
TEXTE_DOUX = "#6B7280"
TEXTE_PALE = "#9AA1B2"
ACCENT = "#4F5BD5"
ACCENT_FONCE = "#4350C4"
ACCENT_PALE = "#ECEEFD"
DANGER = "#D7375A"
DANGER_PALE = "#FDECEF"
SUCCES = "#16A34A"
AVERTISSEMENT = "#D97706"
BARRE = "#161A2C"
BARRE_SURVOL = "#232842"
BARRE_TEXTE = "#B4BAD3"

# Glyphes de la police d'icônes Windows (Segoe Fluent Icons / MDL2 Assets).
ICONES = {
    "accueil": "\ue80f",
    "planning": "\ue787",
    "emploi": "\ue823",
    "matieres": "\ue8f1",
    "epreuves": "\ue7be",
    "travaux": "\ue8a5",
    "preferences": "\ue713",
    "ajouter": "\ue710",
    "modifier": "\ue70f",
    "supprimer": "\ue74d",
    "precedent": "\ue76b",
    "suivant": "\ue76c",
    "generer": "\ue768",
    "cadenas": "\ue72e",
    "alerte": "\ue7ba",
    "annuler": "\ue711",
    "horloge": "\ue823",
    "drapeau": "\ue7c1",
    "coche": "\ue73e",
    "bilan": "\ue9d2",
    "imprimer": "\ue749",
    "sauvegarde": "\ue74e",
    "dossier": "\ue838",
    "restaurer": "\ue777",
    "importer": "\ue723",
    "assistant": "\ue8f2",
    "envoyer": "\ue724",
}


def police_icones() -> str:
    familles = QFontDatabase.families()
    for nom in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if nom in familles:
            return nom
    return ""


def pixmap_icone(nom: str, couleur: str, taille: int = 18) -> QPixmap:
    echelle = 2
    pixmap = QPixmap(taille * echelle, taille * echelle)
    pixmap.fill(Qt.GlobalColor.transparent)
    peintre = QPainter(pixmap)
    peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
    police = QFont(police_icones())
    police.setPixelSize(int(taille * echelle * 0.8))
    peintre.setFont(police)
    peintre.setPen(QColor(couleur))
    peintre.drawText(QRectF(pixmap.rect()), Qt.AlignmentFlag.AlignCenter, ICONES[nom])
    peintre.end()
    pixmap.setDevicePixelRatio(echelle)
    return pixmap


def icone(nom: str, couleur: str = TEXTE, couleur_active: str | None = None, taille: int = 18) -> QIcon:
    """Icône vectorielle Windows, avec une couleur différente une fois cochée."""
    resultat = QIcon()
    resultat.addPixmap(pixmap_icone(nom, couleur, taille), QIcon.Mode.Normal, QIcon.State.Off)
    resultat.addPixmap(pixmap_icone(nom, couleur_active or couleur, taille), QIcon.Mode.Normal, QIcon.State.On)
    resultat.addPixmap(pixmap_icone(nom, TEXTE_PALE, taille), QIcon.Mode.Disabled, QIcon.State.Off)
    return resultat


# --- Composants -------------------------------------------------------------


def carte(parent=None, ombre: bool = True) -> QFrame:
    """Panneau blanc arrondi, légèrement surélevé."""
    cadre = QFrame(parent)
    cadre.setObjectName("carte")
    if ombre:
        effet = QGraphicsDropShadowEffect(cadre)
        effet.setBlurRadius(18)
        effet.setOffset(0, 2)
        effet.setColor(QColor(20, 24, 45, 18))
        cadre.setGraphicsEffect(effet)
    return cadre


def en_tete(titre: str, sous_titre: str = "") -> tuple[QWidget, QHBoxLayout]:
    """En-tête de page : titre et sous-titre à gauche, actions à droite."""
    bloc = QWidget()
    ligne = QHBoxLayout(bloc)
    ligne.setContentsMargins(0, 0, 0, 0)
    textes = QVBoxLayout()
    textes.setSpacing(2)
    libelle = QLabel(titre)
    libelle.setObjectName("titrePage")
    textes.addWidget(libelle)
    if sous_titre:
        sous = QLabel(sous_titre)
        sous.setObjectName("sousTitre")
        sous.setWordWrap(True)
        textes.addWidget(sous)
    ligne.addLayout(textes, 1)
    actions = QHBoxLayout()
    actions.setSpacing(8)
    ligne.addLayout(actions)
    return bloc, actions


def vider(disposition) -> None:
    """Retire et détruit immédiatement tout le contenu d'une disposition."""
    while disposition.count():
        element = disposition.takeAt(0)
        widget = element.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif element.layout() is not None:
            vider(element.layout())


def bouton_role(bouton, role: str):
    """role = « primaire », « danger » ou « discret »."""
    bouton.setProperty("role", role)
    bouton.style().unpolish(bouton)
    bouton.style().polish(bouton)
    return bouton


# --- Feuille de style --------------------------------------------------------

STYLE = f"""
* {{
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10pt;
    color: {TEXTE};
}}
QMainWindow, QDialog, QWidget#contenu, QScrollArea > QWidget > QWidget#defile {{
    background: {FOND};
}}
QToolTip {{
    background: {BARRE}; color: white; border: none; padding: 6px 8px; border-radius: 6px;
}}

/* Barre latérale */
QFrame#barreLaterale {{ background: {BARRE}; }}
QLabel#logo {{ color: white; font-size: 14pt; font-weight: 600; }}
QLabel#logoSous {{ color: #7D84A8; font-size: 9pt; }}
QLabel#sectionNav {{ color: #5E6589; font-size: 8pt; font-weight: 600; letter-spacing: 1px; padding: 14px 14px 4px 14px; }}
QPushButton#nav {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 8px;
    color: {BARRE_TEXTE}; background: transparent; font-size: 10.5pt;
}}
QPushButton#nav:hover {{ background: {BARRE_SURVOL}; color: white; }}
QPushButton#nav:checked {{ background: {ACCENT}; color: white; font-weight: 600; }}
QLabel#piedNav {{ color: #5E6589; font-size: 8pt; padding-left: 4px; }}
QPushButton#lienNav {{ text-align: left; color: {BARRE_TEXTE}; border: none; padding: 6px 8px; font-size: 9pt; }}
QPushButton#lienNav:hover {{ background: {BARRE_SURVOL}; color: white; border-radius: 8px; }}

/* Titres */
QLabel#titrePage {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 20pt; font-weight: 600; }}
QLabel#sousTitre {{ color: {TEXTE_DOUX}; }}
QLabel#titreCarte {{ font-size: 11pt; font-weight: 600; }}
QLabel#doux {{ color: {TEXTE_DOUX}; }}
QLabel#pale {{ color: {TEXTE_PALE}; }}
QLabel#grandChiffre {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 20pt; font-weight: 600; }}
QLabel#vide {{ color: {TEXTE_DOUX}; font-size: 11pt; padding: 40px; }}

/* Cartes */
QFrame#carte {{ background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 12px; }}
QFrame#alerte {{ background: {DANGER_PALE}; border: 1px solid #F5C2CD; border-radius: 10px; }}
QFrame#alerte QLabel {{ color: #8A1C33; background: transparent; }}
/* Assistant : panneau de conversation */
QFrame#conversation {{ background: #F8F9FC; border: 1px solid {BORDURE}; border-radius: 16px; }}
QScrollArea#filAssistant, QScrollArea#filAssistant > QWidget > QWidget {{ background: transparent; }}
QFrame#conversation QWidget#defile {{ background: transparent; }}
QLabel#avatarIA {{
    border-radius: 16px;
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #6C78EE, stop: 1 {ACCENT_FONCE});
}}
QLabel#grandAvatar {{
    border-radius: 32px;
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #7B86F2, stop: 1 {ACCENT_FONCE});
}}
QLabel#titreAccueil {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 17pt; font-weight: 600; }}

/* Bulles */
QFrame#bulleMoi {{
    border-radius: 16px; border-bottom-right-radius: 4px;
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1, stop: 0 #5C68E0, stop: 1 {ACCENT_FONCE});
}}
QFrame#bulleMoi QLabel {{ color: white; background: transparent; font-size: 10.5pt; }}
QFrame#bulleMoi QLabel#heureBulle {{ color: rgba(255, 255, 255, 0.7); font-size: 8pt; }}
QFrame#bulleIA {{
    background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 16px; border-top-left-radius: 4px;
}}
QFrame#bulleIA QLabel {{ background: transparent; font-size: 10.5pt; }}
QFrame#bulleIA QLabel#heureBulle {{ color: {TEXTE_PALE}; font-size: 8pt; }}
QFrame#ligneAttente {{
    background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 16px; border-top-left-radius: 4px;
}}
QLabel#texteAttente {{ color: {TEXTE_DOUX}; font-style: italic; background: transparent; }}

/* Propositions */
QFrame#carteAction, QFrame#carteActionOk, QFrame#carteActionIgnoree, QFrame#carteActionEchec {{
    border-radius: 14px; border: 1px solid #CDD2F7; background: {SURFACE};
}}
QFrame#carteAction {{ border-left: 4px solid {ACCENT}; }}
QFrame#carteActionOk {{ background: #EEFBF2; border: 1px solid #BFE8CC; border-left: 4px solid {SUCCES}; }}
QFrame#carteActionIgnoree {{ background: #F5F6F9; border: 1px solid {BORDURE}; border-left: 4px solid #C3C8D6; }}
QFrame#carteActionEchec {{ background: {DANGER_PALE}; border: 1px solid #F5C2CD; border-left: 4px solid {DANGER}; }}
QLabel#pictoAction {{ background: {ACCENT_PALE}; border-radius: 10px; }}
QFrame#carteActionOk QLabel#pictoAction {{ background: #D9F4E2; }}
QFrame#carteActionIgnoree QLabel#pictoAction {{ background: #ECEEF3; }}
QFrame#carteActionEchec QLabel#pictoAction {{ background: #FAD6DE; }}
QLabel#etiquetteAction {{ color: {ACCENT}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; background: transparent; }}
QFrame#carteActionOk QLabel#etiquetteAction {{ color: {SUCCES}; }}
QFrame#carteActionIgnoree QLabel#etiquetteAction {{ color: {TEXTE_PALE}; }}
QFrame#carteActionEchec QLabel#etiquetteAction {{ color: {DANGER}; }}
QLabel#texteAction {{ color: {TEXTE}; font-weight: 600; background: transparent; }}
QFrame#carteActionIgnoree QLabel#texteAction {{ color: {TEXTE_DOUX}; font-weight: normal; }}

/* Tuiles de l'accueil */
QFrame#tuile {{ background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 14px; }}
QFrame#tuile:hover {{ border: 1px solid {ACCENT}; background: #FBFBFF; }}
QLabel#titreTuile {{ font-weight: 600; background: transparent; }}
QLabel#detailTuile {{ color: {TEXTE_DOUX}; font-size: 9pt; background: transparent; }}

/* Zone de saisie */
QFrame#composeur {{ background: {SURFACE}; border: 1px solid {BORDURE_CHAMP}; border-radius: 16px; }}
QPlainTextEdit#saisieAssistant {{ border: none; background: transparent; padding: 2px; font-size: 10.5pt; }}
QPlainTextEdit#saisieAssistant:focus {{ border: none; }}
QLabel#pieceJointe {{
    background: {ACCENT_PALE}; color: {ACCENT_FONCE}; border-radius: 10px; padding: 5px 10px; font-weight: 600;
}}
QPushButton#boutonEnvoyer {{ border-radius: 18px; padding: 8px 18px; }}
QFrame#bandeau {{ background: {ACCENT_PALE}; border: 1px solid #CDD2F7; border-radius: 10px; }}
QFrame#bandeau QLabel {{ color: {ACCENT_FONCE}; background: transparent; font-weight: 600; }}
QLabel#pastille {{
    background: {ACCENT_PALE}; color: {ACCENT_FONCE}; border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
QLabel#pastilleDanger {{
    background: {DANGER_PALE}; color: {DANGER}; border-radius: 11px; padding: 3px 10px; font-weight: 600;
}}
QGroupBox {{
    background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 12px;
    margin-top: 26px; padding: 16px 14px 12px 14px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 4px;
    padding: 0 4px; font-size: 11pt; color: {TEXTE};
}}
QGroupBox QLabel, QGroupBox QCheckBox {{ font-weight: normal; background: transparent; }}

/* Boutons */
QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDURE_CHAMP}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ background: #F0F2F8; border-color: #C3C8D6; }}
QPushButton:pressed {{ background: #E6E9F2; }}
QPushButton:disabled {{ color: {TEXTE_PALE}; background: {FOND}; }}
QPushButton:default {{ border-color: {ACCENT}; }}
QPushButton[role="primaire"] {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600;
}}
QPushButton[role="primaire"]:hover {{ background: {ACCENT_FONCE}; border-color: {ACCENT_FONCE}; }}
QPushButton[role="danger"] {{ color: {DANGER}; }}
QPushButton[role="danger"]:hover {{ background: {DANGER_PALE}; border-color: #F3B8C3; }}
QPushButton[role="discret"] {{ border: none; background: transparent; padding: 6px 8px; }}
QPushButton#segment {{ border-radius: 16px; padding: 6px 14px; }}
QPushButton#segment:checked {{ background: {TEXTE}; border-color: {TEXTE}; color: white; font-weight: 600; }}
QPushButton[role="discret"]:hover {{ background: #E9EBF3; }}

/* Champs */
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QDateTimeEdit, QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDURE_CHAMP}; border-radius: 7px; padding: 5px 8px;
    min-height: 20px; selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus,
QDateEdit:focus, QDateTimeEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QTimeEdit:disabled, QDateEdit:disabled,
QDateTimeEdit:disabled, QComboBox:disabled {{ background: {FOND}; color: {TEXTE_PALE}; }}
QAbstractSpinBox {{ padding-left: 8px; padding-right: 24px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none; background: transparent; margin-right: 2px;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #EEF0F6; border-radius: 4px; }}
QAbstractSpinBox::up-arrow {{ image: url({IMAGES}/chevron_haut.svg); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url({IMAGES}/chevron_bas.svg); width: 10px; height: 10px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none; background: transparent;
}}
QComboBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow {{
    image: url({IMAGES}/chevron_bas.svg); width: 11px; height: 11px;
}}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1.5px solid #B9BFCD; border-radius: 4px; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({IMAGES}/coche.svg); }}
QCheckBox::indicator:disabled {{ background: {FOND}; border-color: #D5D9E4; }}
QCheckBox::indicator:checked:disabled {{ background: #B9BFE8; border-color: #B9BFE8; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1.5px solid #B9BFCD; border-radius: 9px; background: {SURFACE};
}}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{
    border: 1.5px solid {ACCENT};
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
                                stop: 0 {ACCENT}, stop: 0.42 {ACCENT}, stop: 0.5 {SURFACE}, stop: 1 {SURFACE});
}}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDURE}; selection-background-color: {ACCENT_PALE};
    selection-color: {TEXTE}; outline: none; padding: 4px;
}}

/* Tableaux */
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 12px; gridline-color: transparent;
    alternate-background-color: #FAFBFD; selection-background-color: {ACCENT_PALE}; selection-color: {TEXTE};
    outline: none;
}}
QTableWidget::item {{ padding: 4px 10px; border-bottom: 1px solid #F0F1F6; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXTE_DOUX}; border: none; border-bottom: 1px solid {BORDURE};
    padding: 10px; font-weight: 600; font-size: 9pt;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

/* Défilement */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CDD1DD; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #B5BACA; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CDD1DD; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {FOND}; color: {TEXTE_PALE}; font-size: 9pt; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDURE}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_PALE}; color: {TEXTE}; }}
QMenu::separator {{ height: 1px; background: {BORDURE}; margin: 4px 6px; }}
QMessageBox QLabel {{ min-width: 280px; }}
"""


def appliquer_theme(application: QApplication) -> None:
    """Style Fusion + palette claire + feuille de style : rendu identique partout."""
    application.setStyle("Fusion")
    palette = QPalette()
    for role, couleur in (
        (QPalette.ColorRole.Window, FOND),
        (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, "#FAFBFD"),
        (QPalette.ColorRole.Text, TEXTE),
        (QPalette.ColorRole.WindowText, TEXTE),
        (QPalette.ColorRole.ButtonText, TEXTE),
        (QPalette.ColorRole.Button, SURFACE),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
        (QPalette.ColorRole.PlaceholderText, TEXTE_PALE),
        (QPalette.ColorRole.ToolTipBase, BARRE),
        (QPalette.ColorRole.ToolTipText, "#FFFFFF"),
    ):
        palette.setColor(role, QColor(couleur))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)
