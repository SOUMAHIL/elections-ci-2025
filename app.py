import streamlit as st
import pandas as pd
import duckdb
import os
import re # Pour un nettoyage SQL plus propre
from langchain_openai import ChatOpenAI
from scripts.router import HybridRouter 

# --- CONFIGURATION DE L'INTERFACE ---
st.set_page_config(page_title="IA Élections CI 2025 - Mode Hybride", layout="wide")
st.title("🗳️ Analyste IA - Élections CI 2025")
st.subheader("Système Hybride : Intelligence Statistique & Sémantique")

# --- BARRE LATÉRALE (Sidebar) ---
st.sidebar.header("🔑 Authentification")
api_key = st.sidebar.text_input("Clé API OpenAI", type="password")

# --- FONCTION DE SÉCURITÉ (Guardrail) ---
def validate_sql(query):
    """Vérifie que la requête générée par l'IA ne contient pas de commandes destructrices."""
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE"]
    for word in forbidden:
        if word in query.upper():
            return False, f"⚠️ Action interdite détectée : {word}"
    return True, query

# --- LOGIQUE PRINCIPALE DE L'APPLICATION ---
if api_key:
    try:
        # Initialisation du cerveau hybride
        router = HybridRouter(api_key)
        llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)
        db_path = "data/elections_ci.db"

        # Champ de saisie utilisateur
        user_input = st.chat_input("Posez votre question (ex: Qui gagne à Tiapum ?)")

        if user_input:
            # 1. NORMALISATION (Entity Resolution)
            # On utilise la fonction robuste du router pour corriger 'sifié' -> 'SIFIE'
            clean_question = router.normalize_query(user_input)
            st.write(f"DEBUG - Original: {user_input} | Corrigé: {clean_question}")
            
            with st.chat_message("user"):
                st.write(user_input)
                # On informe l'utilisateur de la correction
                if clean_question.lower() != user_input.lower():
                    st.caption(f"✨ Question optimisée : *{clean_question}*")

            # 2. CLASSIFICATION D'INTENTION
            intent = router.classify_intent(clean_question)
            
            with st.chat_message("assistant"):
                # --- CHEMIN A : MOTEUR SQL ---
                if intent == "SQL":
                    status = st.status("🔍 Analyse des données en cours...", state="running")
                    
                    prompt_sql = f"""Tu es un expert SQL DuckDB. 
                    Schéma des tables :
                    - circonscriptions (code_circ, nom_circ, nb_inscrits, nb_votants, nom_region)
                    - resultats (code_circ, nom_candidat, nom_parti, voix_obtenues, est_elu)

                    RÈGLES :
                    1. Jointure : resultats.code_circ = circonscriptions.code_circ
                    2. 'resultats' contient déjà 'nom_parti'.
                    
                    Question : {clean_question}
                    Réponds UNIQUEMENT avec la requête SQL brute."""

                    response_sql = llm.invoke(prompt_sql).content
                    
                    # Nettoyage SQL robuste (enlève le markdown ```sql ... ```)
                    sql_query = re.sub(r"```sql|```", "", response_sql).strip()

                    is_safe, final_query = validate_sql(sql_query)
                    
                    if is_safe:
                        # Utilisation d'une connexion temporaire pour éviter les verrous
                        with duckdb.connect(db_path) as conn:
                            df_result = conn.execute(final_query).df()
                        
                        status.update(label="✅ Analyse terminée", state="complete")

                        if df_result.empty:
                            st.info("Aucun résultat statistique trouvé.")
                        else:
                            st.code(final_query, language="sql")
                            st.dataframe(df_result, use_container_width=True)

                            # --- GRAPHIQUE ---
                            nums = df_result.select_dtypes(include=['number']).columns
                            txts = df_result.select_dtypes(include=['object']).columns
                            
                            if len(nums) > 0 and len(txts) > 0:
                                st.subheader("📊 Visualisation")
                                st.bar_chart(data=df_result, x=txts[0], y=nums[0])
                    else:
                        status.update(label="❌ Sécurité SQL", state="error")
                        st.error(is_safe)

                # --- CHEMIN B : MOTEUR RAG ---
                else:
                    status = st.status("📖 Recherche sémantique...", state="running")
                    # On envoie bien la question NETTOYÉE au RAG
                    answer = router.run_rag_search(clean_question)
                    status.update(label="✅ Recherche terminée", state="complete")
                    
                    st.markdown(f"### Réponse de l'Agent\n{answer}")
                    st.caption("ℹ️ Source : Documents officiels (Fuzzy Lookup)")

    except Exception as e:
        st.error("Une erreur technique est survenue.")
        st.exception(e) # Affiche le traceback complet pour débugger
else:
    st.info("👋 Veuillez saisir votre clé API OpenAI pour commencer.")