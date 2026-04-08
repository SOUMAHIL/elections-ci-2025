import duckdb # DuckDB est une base de données relationnelle en mémoire, idéale pour les analyses rapides et les manipulations de données.
import os

# ce script sert à Prendre un CSV , Le transformer en base de données structurée et Créer des tables propres pour analyse.
# Chemins des fichiers
CSV_PATH = "output/resultats_officiels_2025_FINAL.csv" # fichier source (CSV)
DB_PATH = "data/elections_ci.db" # la base de données cible


def setup_database():
    if not os.path.exists(CSV_PATH): # on vérifies si le CSV existe
        print(f"❌ Erreur : Le fichier {CSV_PATH} est introuvable.") # si le fichier n'existe pas, on affiche une erreur et on quitte la fonction
        return

    print(f"🚀 Initialisation de la base de données : {DB_PATH}") 
    
    # Connexion à DuckDB
    con = duckdb.connect(DB_PATH) # on se connecte à la base de données (si elle n'existe pas, elle sera créée automatiquement)

    try:
        # 1. Chargement du CSV dans une table brute temporaire
        con.execute(f"CREATE OR REPLACE TABLE raw_data AS SELECT * FROM read_csv_auto('{CSV_PATH}')")

        # 2. Création de la table REGIONS
        con.execute("""
            CREATE OR REPLACE TABLE regions AS 
            SELECT DISTINCT Region as nom_region 
            FROM raw_data 
            WHERE Region IS NOT NULL;
        """)
        print("✅ Table 'regions' créée.")

        # 3. Création de la table PARTIS
        con.execute("""
            CREATE OR REPLACE TABLE partis AS 
            SELECT DISTINCT Parti as nom_parti 
            FROM raw_data 
            WHERE Parti IS NOT NULL;
        """)
        print("✅ Table 'partis' créée.")

        # 4. Création de la table CIRCONSCRIPTIONS
        con.execute("""
            CREATE OR REPLACE TABLE circonscriptions AS 
            SELECT DISTINCT 
                split_part(Circonscription, ' - ', 1) as code_circ,
                split_part(Circonscription, ' - ', 2) as nom_circ,
                Inscrits as nb_inscrits,
                Votants as nb_votants,
                Suf_Exprimes as suf_exprimes,
                Region as nom_region
            FROM raw_data;
        """)
        print("✅ Table 'circonscriptions' créée.")

        # 5. Création de la table RESULTATS
        con.execute("""
            CREATE OR REPLACE TABLE resultats AS 
            SELECT 
                split_part(Circonscription, ' - ', 1) as code_circ,
                Candidat as nom_candidat,
                Parti as nom_parti,
                Score as voix_obtenues,
                Elu as est_elu
            FROM raw_data;
        """)
        print("✅ Table 'resultats' créée.")

        # 6. Nettoyage : on supprime la table brute
        con.execute("DROP TABLE raw_data")

        # --- PETIT TEST DE VÉRIFICATION ---
        # On comptes: nombres de régions,circonscriptions, partis et lignes de résultats pour s'assurer que tout a été importé correctement
        print("\n📊 RÉSUMÉ DE L'IMPORTATION :")
        res = con.execute("""
            SELECT 
                (SELECT COUNT(*) FROM regions),
                (SELECT COUNT(*) FROM circonscriptions),
                (SELECT COUNT(*) FROM partis),
                (SELECT COUNT(*) FROM resultats)
        """).fetchone() # On récupères les résultats
        
        # zone d'affichage des résultats
        print(f"- Régions : {res[0]}")
        print(f"- Circonscriptions : {res[1]}")
        print(f"- Partis politiques : {res[2]}")
        print(f"- Lignes de résultats : {res[3]}")

    # Si problème : On captures l’erreur et on l’affiche pour faciliter le debug
    except Exception as e:
        print(f"❌ Une erreur est survenue : {e}")
    finally:
        con.close() # fermer la connexion à la DB

if __name__ == "__main__": # Lance la fonction si script exécuté directement
    setup_database() 