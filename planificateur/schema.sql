-- Schéma version 1. Dates en texte ISO (AAAA-MM-JJ, AAAA-MM-JJTHH:MM), heures en HH:MM.

CREATE TABLE matieres (
    id          INTEGER PRIMARY KEY,
    nom         TEXT NOT NULL,
    code        TEXT NOT NULL DEFAULT '',
    coefficient REAL NOT NULL DEFAULT 1 CHECK (coefficient > 0),
    difficulte  INTEGER NOT NULL DEFAULT 3 CHECK (difficulte BETWEEN 1 AND 5),
    maitrise    INTEGER NOT NULL DEFAULT 3 CHECK (maitrise BETWEEN 1 AND 5),
    couleur     TEXT NOT NULL DEFAULT '#4C72B0',
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE activites_fixes (
    id              INTEGER PRIMARY KEY,
    nom             TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'cours',
    jour_semaine    INTEGER CHECK (jour_semaine BETWEEN 0 AND 6),
    date            TEXT,
    heure_debut     TEXT NOT NULL,
    heure_fin       TEXT NOT NULL,
    valide_du       TEXT,
    valide_au       TEXT,
    marge_avant_min INTEGER NOT NULL DEFAULT 0 CHECK (marge_avant_min >= 0),
    marge_apres_min INTEGER NOT NULL DEFAULT 0 CHECK (marge_apres_min >= 0),
    matiere_id      INTEGER REFERENCES matieres(id) ON DELETE SET NULL,
    CHECK (heure_fin > heure_debut),
    CHECK ((jour_semaine IS NULL) <> (date IS NULL))
);

CREATE TABLE exceptions_activite (
    id          INTEGER PRIMARY KEY,
    activite_id INTEGER NOT NULL REFERENCES activites_fixes(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    UNIQUE (activite_id, date)
);

CREATE TABLE epreuves (
    id          INTEGER PRIMARY KEY,
    matiere_id  INTEGER NOT NULL REFERENCES matieres(id) ON DELETE RESTRICT,
    type        TEXT NOT NULL DEFAULT 'composition',
    intitule    TEXT NOT NULL DEFAULT '',
    debut       TEXT NOT NULL,
    fin         TEXT NOT NULL,
    chapitres   TEXT NOT NULL DEFAULT '',
    importance  INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    difficulte  INTEGER NOT NULL DEFAULT 3 CHECK (difficulte BETWEEN 1 AND 5),
    preparation INTEGER NOT NULL DEFAULT 1 CHECK (preparation BETWEEN 1 AND 5),
    etat        TEXT NOT NULL DEFAULT 'a_preparer',
    CHECK (fin > debut)
);

CREATE TABLE travaux (
    id                INTEGER PRIMARY KEY,
    intitule          TEXT NOT NULL,
    matiere_id        INTEGER NOT NULL REFERENCES matieres(id) ON DELETE RESTRICT,
    type              TEXT NOT NULL DEFAULT 'devoir',
    echeance          TEXT NOT NULL,
    date_cible        TEXT,
    minutes_estimees  INTEGER NOT NULL CHECK (minutes_estimees > 0),
    minutes_restantes INTEGER NOT NULL CHECK (minutes_restantes >= 0),
    importance        INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    etat              TEXT NOT NULL DEFAULT 'a_faire',
    notes             TEXT NOT NULL DEFAULT ''
);

CREATE TABLE sous_taches (
    id         INTEGER PRIMARY KEY,
    travail_id INTEGER NOT NULL REFERENCES travaux(id) ON DELETE CASCADE,
    intitule   TEXT NOT NULL,
    terminee   INTEGER NOT NULL DEFAULT 0,
    ordre      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE seances (
    id                 INTEGER PRIMARY KEY,
    type               TEXT NOT NULL,
    debut              TEXT NOT NULL,
    fin                TEXT NOT NULL,
    matiere_id         INTEGER REFERENCES matieres(id) ON DELETE SET NULL,
    epreuve_id         INTEGER REFERENCES epreuves(id) ON DELETE CASCADE,
    travail_id         INTEGER REFERENCES travaux(id) ON DELETE CASCADE,
    statut             TEXT NOT NULL DEFAULT 'prevue',
    minutes_effectuees INTEGER,
    origine            TEXT NOT NULL DEFAULT 'auto',
    verrouillee        INTEGER NOT NULL DEFAULT 0,
    CHECK (fin > debut)
);

CREATE INDEX idx_seances_debut ON seances(debut);
CREATE INDEX idx_epreuves_debut ON epreuves(debut);
CREATE INDEX idx_travaux_echeance ON travaux(echeance);

CREATE TABLE parametres (
    cle    TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);
