import os
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain.chains import create_sql_query_chain
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool

# 1. Connexion de l'agent à la base DuckDB 
# SQLDatabase permet au LLM de : voir les tables et comprendre les colonnes
db = SQLDatabase.from_uri("duckdb:///data/elections_ci.db")

# Cette fonction construit le “cerveau”
def get_sql_chain(api_key):
    # Modèle de cerveau (LLM) de ChatOpenAI : GPT-4o
    llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)
    
    # Chaîne de génération de requête: Input = question de l'utilisateur, Output = requête SQL générée par le LLM
    generate_query = create_sql_query_chain(llm, db)
    
    # Outil d'exécution
    # cet outil sert à : prendre la requête SQL,l’exécuter dans la base  et retourner les résultats
    execute_query = QuerySQLDataBaseTool(db=db)# db=db: puisque QuerySQLDataBaseTool est une classe et cette classe attend un paramètre db, Donc on lui donnes db=db “Le paramètre db de l’outil reçoit ma variable db”
    
    return generate_query, execute_query # On sépares : génération et exécution

# On ajoutes une sécurité contre les requêtes dangereuses
def validate_sql(query):
    """Guardrail : Vérifie que la requête est uniquement un SELECT."""
    forbidden_words = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE"] # On bloques : suppression de tables,modification de données
    query_upper = query.upper() # On mets en majuscule pour éviter les contournements
    for word in forbidden_words: 
        if word in query_upper: # Si un mot interdit est détecté → blocage
            return False, f"Requête interdite détectée : {word}" # Tu refuses la requête
    return True, query # Sinon → autorisé