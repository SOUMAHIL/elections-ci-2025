# Assistant IA Élections CI 2025 — Projet Agentic AI

Cet assistant permet d'interroger les résultats des élections locales 2025 via une interface conversationnelle. Il utilise un routeur intelligent pour basculer entre :

* Moteur SQL (DuckDB) : Pour les calculs précis (Top 3, sommes de voix, statistiques).

* Moteur RAG (FAISS) : Pour les recherches contextuelles et les détails par circonscription issues des documents PDF officiels.

## Structure du dépôt
.
├── data/
│   ├── elections_ci.db          — Base de données DuckDB structurée
│   ├── election_dict.json       — Dictionnaire des localités (Désambiguïsation)
│   ├── faiss_index/             — Index vectoriel pour la recherche RAG
│   └── EDAN_2025_..._DETAILS.pdf — Source brute (PDF officiel)
│
├── output/
│   └── resultats_officiels_2025_FINAL.csv — Données extraites et nettoyées
│
├── scripts/
│   ├── ingest.py                — Extraction complexe (PDF -> CSV) avec PDFPlumber
│   ├── setup_db.py              — Pipeline ETL (CSV -> SQL DuckDB)
│   ├── build_dictionary.py      — Génération du référentiel géographique
│   ├── create_embeddings.py     — Pipeline RAG (CSV -> FAISS Vector Store)
│   └── router.py                — Logique de classification (SQL vs RAG vs Greeting)
│   └── run_benchmark.py         
├── app.py                       — Interface utilisateur Streamlit (Multi-agent)

## Démarrage rapide

### 1.Création de l'environnement virtuel

```bash
python -m venv .venv
source .venv/bin/activate  # Sur Windows: .venv\Scripts\activate
```
### 2.Installation des bibliothèques
```bash
pip install -r requirements.txt
```
### 3. Initialisation des données (Pipeline ETL)
```bash
python scripts/ingest.py            # Extrait les données du PDF
python scripts/setup_db.py          # Crée la base SQL DuckDB
python scripts/build_dictionary.py  # Crée le dictionnaire de recherche
python scripts/create_embeddings.py # Génère l'index pour le RAG
```

### 4. Lancer l'Assistant
```bash
streamlit run app.py
```
