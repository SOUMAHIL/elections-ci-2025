import streamlit as st
import pandas as pd
import duckdb
import os
import re
import time
from langchain_openai import ChatOpenAI
from scripts.router import HybridRouter
from dotenv import load_dotenv
from langfuse.langchain import CallbackHandler

# Charge les clés du fichier .env
load_dotenv()

# Initialise le handler Langfuse
langfuse_handler = CallbackHandler()

# IMPORT DES PROMPTS DÉCOUPLÉS
from scripts.prompts import SQL_SYSTEM_PROMPT, CLARIFICATION_PROMPT, FINAL_ANSWER_PROMPT

# Initialisation du logger


# --- INITIALISATION DE LA MÉMOIRE ---
if "messages" not in st.session_state:
    st.session_state.messages = [] 
if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = False
if "options" not in st.session_state:
    st.session_state.options = []

st.set_page_config(page_title="IA Élections CI 2025", layout="wide")
st.title("🗳️ Assistant IA - Élections CI 2025")
st.subheader("Niveau 4 : Observabilité et Robustesse")

api_key = st.sidebar.text_input("Clé API OpenAI", type="password")

def validate_sql(query):
    """Sécurité : Bloque les requêtes de modification de la base."""
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE", "CREATE"]
    for word in forbidden:
        if word in query.upper():
            return False, f"⚠️ Action interdite par sécurité : {word}"
    return True, query

if api_key:
    try:
        router = HybridRouter(api_key)
        llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)
        db_path = "data/elections_ci.db"

        # 1. AFFICHAGE DE L'HISTORIQUE
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("data") is not None: 
                    st.dataframe(message["data"])

        # 2. GESTION DE LA SAISIE
        user_input = st.chat_input("Posez votre question (ex: Qui gagne à Yopougon ?)")
        current_query = user_input
        
        # Récupération automatique après un clic sur bouton de clarification
        if not user_input and "final_query" in st.session_state:
            current_query = st.session_state.pop("final_query")

        if current_query:
            
            
            if user_input:
                st.session_state.pending_clarification = False
                st.session_state.options = []
                st.session_state.messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"): st.markdown(user_input)
                

            # --- ÉTAPE A : ROUTAGE & DÉSAMBIGUÏSATION ---
            clean_question = router.normalize_query(current_query)
            
            if st.session_state.get("pending_clarification"):
                with st.chat_message("assistant"):
                     # Utilisation du prompt de clarification expert
                     clarif_text = llm.invoke(f"{CLARIFICATION_PROMPT}\nQuestion: {current_query}" ,config={"callbacks": [langfuse_handler]}).content
                     st.write(f"🔎 {clarif_text}")
                     
                     cols = st.columns(2)
                     for i, option in enumerate(st.session_state.options):
                         if cols[i % 2].button(option, key=f"btn_{i}"):
                            original_question = st.session_state.messages[-1]["content"] if st.session_state.messages else current_query
                            st.session_state.final_query = f"{original_question} à {option}"
                            st.session_state.pending_clarification = False
                            st.session_state.options = []
                            st.rerun()
                st.stop()            
            
            intent = router.classify_intent(clean_question, callbacks=[langfuse_handler])
            

            # --- ÉTAPE B : EXÉCUTION ---
            with st.chat_message("assistant"):
                response_content = ""
                df_to_save = None

                if intent == "SQL":
                    status = st.status("🔍 Analyse statistique de la base...", state="running")
                    
                    # Utilisation du SQL_SYSTEM_PROMPT expert (incluant ton audit DB)
                    full_sql_prompt = f"{SQL_SYSTEM_PROMPT}\n\nQuestion : {clean_question}"
                    
                    sql_raw = llm.invoke(full_sql_prompt, config={"callbacks": [langfuse_handler]}).content
                    
                    # Nettoyage de la sortie pour n'avoir que le code
                    match = re.search(r"(SELECT|WITH).*?;", sql_raw, re.DOTALL | re.IGNORECASE)
                    sql_clean = match.group(0) if match else sql_raw.strip()
                    sql_clean = re.sub(r"```sql|```", "", sql_clean).strip()
                    
                    st.code(sql_clean, language="sql")
                    is_safe, final_sql = validate_sql(sql_clean)
                    
                    if is_safe:
                        try:
                            with duckdb.connect(db_path) as conn:
                                df_result = conn.execute(final_sql).df()
                            
                            if not df_result.empty:
                                st.dataframe(df_result, use_container_width=True)
                                df_to_save = df_result
                                
                                # Utilisation du FINAL_ANSWER_PROMPT pour une analyse pro
                                analysis_prompt = f"{FINAL_ANSWER_PROMPT}\nQuestion: {clean_question}\nDonnées: {df_result.to_string()}"
                                response_content = llm.invoke(analysis_prompt, config={"callbacks": [langfuse_handler]}).content
                                st.markdown(response_content)
                            else:
                                response_content = "Aucun résultat trouvé pour cette recherche."
                                st.info(response_content)
                            status.update(label="✅ Analyse terminée", state="complete")
                        except Exception as e:
                            status.update(label="❌ Erreur technique", state="error")
                            st.error(f"Détail : {e}")
                    else:
                        st.error(is_safe)

                elif intent == "CLARIFY":
                    response_content = llm.invoke(f"{CLARIFICATION_PROMPT}\nQuestion: {clean_question}", config={"callbacks": [langfuse_handler]}).content
                    st.info(response_content)
                
                elif intent == "GREETING":
                    response_content = "Bonjour ! Je suis l'assistant expert pour les élections 2025. Comment puis-je vous aider ?"
                    st.markdown(response_content)
                
                else: # Moteur RAG (Recherche Documentaire)
                    response_content = router.run_rag_search(clean_question, history=st.session_state.messages[-3:],callbacks=[langfuse_handler])
                    st.markdown(response_content)
                
                # --- LOG PERFORMANCE ---
               
                if response_content:
                    st.session_state.messages.append({"role": "assistant", "content": response_content, "data": df_to_save})

    except Exception as e:
        st.error(f"Erreur système critique : {e}")