"""
setup_db.py — Auto-détection du format CSV
===========================================
Détecte automatiquement les colonnes disponibles et construit
la DB avec les bons noms pour le SQL_SYSTEM_PROMPT.

Tables créées (noms utilisés par le prompt SQL) :
  circonscriptions : code_circ, nom_circ, nom_region, nb_inscrits,
                     nb_votants, suf_exprimes, taux_participation
  resultats        : code_circ, nom_candidat, nom_parti,
                     voix_obtenues, pourcentage, est_elu
"""

import duckdb
import os

CSV_PATH = "output/resultats_officiels_2025_FINAL.csv"
DB_PATH  = "data/elections_ci.db"


def setup_database():
    if not os.path.exists(CSV_PATH):
        print(f"❌ CSV introuvable : {CSV_PATH}")
        print("   Lance d'abord : python ingest.py")
        return False

    print(f"🚀 Construction DB depuis : {CSV_PATH}")
    con = duckdb.connect(DB_PATH)

    try:
        # Charger le CSV
        con.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS
            SELECT * FROM read_csv_auto('{CSV_PATH}', HEADER=TRUE)
        """)

        # Détecter les colonnes disponibles
        colonnes = [c[0].lower() for c in con.execute("DESCRIBE raw_data").fetchall()]
        print(f"   Colonnes détectées : {colonnes}")

        # ── Détecter le format ────────────────────────────────────────
        # Nouveau format (ingest.py) : colonnes en minuscules
        est_nouveau = "nom_candidat" in colonnes and "voix_obtenues" in colonnes

        # Ancien format (Gemini) : colonnes avec majuscules
        est_ancien  = "candidat" in colonnes or "score" in colonnes

        print(f"   Format : {'✅ nouveau (ingest.py)' if est_nouveau else '⚠️  ancien (Gemini) — renommage automatique'}")

        # ── Table CIRCONSCRIPTIONS ────────────────────────────────────
        if est_nouveau:
            # Les colonnes correspondent déjà au prompt SQL
            circ_query = """
                CREATE OR REPLACE TABLE circonscriptions AS
                SELECT
                    code_circ,
                    MAX(nom_circ)    AS nom_circ,
                    MAX(region)      AS nom_region,
                    MAX(nb_bv)       AS nb_bv,
                    MAX(inscrits)    AS nb_inscrits,
                    MAX(votants)     AS nb_votants,
                    MAX(suf_exprimes) AS suf_exprimes,
                    ROUND(
                        MAX(votants) * 100.0 / NULLIF(MAX(inscrits), 0), 2
                    ) AS taux_participation
                FROM raw_data
                GROUP BY code_circ
            """
            res_query = """
                CREATE OR REPLACE TABLE resultats AS
                SELECT
                    code_circ,
                    nom_candidat,
                    parti        AS nom_parti,
                    voix_obtenues,
                    pourcentage,
                    est_elu,
                    page_source
                FROM raw_data
            """
        else:
            # Ancien format : renommage des colonnes Gemini
            # Extraire code_circ depuis "042 - KOUMASSI, COMMUNE"
            circ_query = """
                CREATE OR REPLACE TABLE circonscriptions AS
                SELECT
                    TRY_CAST(SPLIT_PART(Circonscription, ' - ', 1) AS INTEGER) AS code_circ,
                    SPLIT_PART(Circonscription, ' - ', 2)  AS nom_circ,
                    MAX(Region)       AS nom_region,
                    MAX(NB_BV)        AS nb_bv,
                    MAX(Inscrits)     AS nb_inscrits,
                    MAX(Votants)      AS nb_votants,
                    MAX(Suf_Exprimes) AS suf_exprimes,
                    ROUND(
                        MAX(Votants) * 100.0 / NULLIF(MAX(Inscrits), 0), 2
                    ) AS taux_participation
                FROM raw_data
                GROUP BY SPLIT_PART(Circonscription, ' - ', 1),
                         SPLIT_PART(Circonscription, ' - ', 2)
            """
            res_query = """
                CREATE OR REPLACE TABLE resultats AS
                SELECT
                    TRY_CAST(SPLIT_PART(Circonscription, ' - ', 1) AS INTEGER) AS code_circ,
                    Candidat      AS nom_candidat,
                    Parti         AS nom_parti,
                    Score         AS voix_obtenues,
                    Pourcentage   AS pourcentage,
                    CASE WHEN UPPER(Elu) = 'OUI' THEN 'OUI' ELSE 'NON' END AS est_elu,
                    0             AS page_source
                FROM raw_data
            """

        con.execute(circ_query)
        print("✅ Table 'circonscriptions' créée")

        con.execute(res_query)
        print("✅ Table 'resultats' créée")

        con.execute("DROP TABLE IF EXISTS raw_data")

        # ── Validation ────────────────────────────────────────────────
        nb_circs = con.execute("SELECT COUNT(*) FROM circonscriptions").fetchone()[0]
        nb_cands = con.execute("SELECT COUNT(*) FROM resultats").fetchone()[0]
        nb_elus  = con.execute(
            "SELECT COUNT(*) FROM resultats WHERE est_elu = 'OUI'"
        ).fetchone()[0]
        nb_taux  = con.execute(
            "SELECT COUNT(*) FROM circonscriptions WHERE taux_participation > 0"
        ).fetchone()[0]

        print(f"\n📊 BASE DE DONNÉES :")
        print(f"   Circonscriptions : {nb_circs}")
        print(f"   Candidats        : {nb_cands}")
        print(f"   Élus             : {nb_elus}")
        print(f"   Taux > 0         : {nb_taux}/{nb_circs} {'✅' if nb_taux > 0 else '❌'}")

        if nb_elus == 0:
            print("\n   ⚠️  ATTENTION : 0 élus détectés !")
            print("   Vérifier la colonne 'est_elu' dans le CSV")
            sample = con.execute(
                "SELECT est_elu, COUNT(*) FROM resultats GROUP BY est_elu LIMIT 5"
            ).fetchall()
            print(f"   Valeurs de est_elu : {sample}")

        # Test gagnant circ 2
        test = con.execute("""
            SELECT r.nom_candidat, r.nom_parti, r.voix_obtenues, c.taux_participation
            FROM resultats r JOIN circonscriptions c ON r.code_circ = c.code_circ
            WHERE r.code_circ = 2 AND r.est_elu = 'OUI'
            LIMIT 1
        """).fetchone()

        if test:
            print(f"\n   Test circ 002 : {test[0]} ({test[1]}) — {test[2]} voix")
            print(f"   Taux circ 002  : {test[3]}% ✅")
        else:
            print("\n   ⚠️  Test circ 002 : aucun élu trouvé")

        print(f"\n✅ Base sauvegardée : {DB_PATH}")
        return True

    except Exception as e:
        print(f"❌ Erreur : {e}")
        import traceback; traceback.print_exc()
        return False
    finally:
        con.close()


if __name__ == "__main__":
    setup_database()