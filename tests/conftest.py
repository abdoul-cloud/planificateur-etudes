"""Réglages communs des tests.

Les tests d'interface s'exécutent sans affichage (plateforme Qt « offscreen »).
Une seule application Qt sert à toute la session ; à la fin, toutes les
fenêtres sont détruites avant elle, sinon Python peut planter en quittant
alors que tous les tests ont réussi.
"""

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def application():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pytest_sessionfinish(session, exitstatus):
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    application = QApplication.instance()
    if application is None:
        return
    for fenetre in QApplication.topLevelWidgets():
        fenetre.close()
        fenetre.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()
