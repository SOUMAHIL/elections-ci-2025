import duckdb

con = duckdb.connect("data/elections_ci.db")

print("🔍 ANALYSE RAPIDE DES DONNÉES SQL")
print("-" * 40)

# 1. Top 5 des circonscriptions avec le plus d'inscrits
print("\n1. TOP 5 DES CIRCONSCRIPTIONS (NB INSCRITS) :")
query1 = """
    SELECT nom_circ, nb_inscrits 
    FROM circonscriptions 
    ORDER BY nb_inscrits DESC 
    LIMIT 5
"""
print(con.execute(query1).df())

# 2. Score total par grand Parti (Top 5)
print("\n2. TOP 5 DES PARTIS PAR NOMBRE DE VOIX TOTALES :")
query2 = """
    SELECT nom_parti, SUM(voix_obtenues) as total_voix
    FROM resultats
    GROUP BY nom_parti
    ORDER BY total_voix DESC
    LIMIT 5
"""
print(con.execute(query2).df())

# 3. Vérification des élus
print("\n3. NOMBRE D'ÉLUS DÉTECTÉS :")
query3 = "SELECT COUNT(*) FROM resultats WHERE est_elu = 'OUI'"
print(f"Total élus : {con.execute(query3).fetchone()[0]}")

con.close()