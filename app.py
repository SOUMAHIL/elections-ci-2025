# Cette app est un assistant IA pour analyser les élections en Côte d’Ivoire 🇨🇮
#Elle peut:
# discuter avec l’utilisateur (chat),interroger une base DuckDB,afficher les tableaux graphiques,
# faire du rag(recherche documentaire) et utiliser un LLM  pour interpréter les résultats
# le rag est un moteur de recherche intelligent qui va chercher dans une base de connaissances (ici les résultats électoraux) pour répondre précisément à la question posée

# import des packages nécessaires
import streamlit as st
import pandas as pd
import duckdb
import os
import re #-> pour nettoyer les réponses SQL du LLM
from langchain_openai import ChatOpenAI #-> pour interagir avec le modèle de langage (LLM) et générer des réponses basées sur les prompts
from scripts.router import HybridRouter #-> cerveau personnalisé: le routeur décide:SQL,RAG,conversation...

# --- INITIALISATION DE LA MÉMOIRE ET DES ÉTATS ---
# 
if "messages" not in st.session_state:
    st.session_state.messages = [] # stocke l'historique complet de la conversation
if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = False # gère les ambiguïtés et les clarifications en attente

# --- CONFIGURATION DE L'INTERFACE ---
# utlisation de la bibliothèque Streamlit pour créer une interface utilisateur simple et interactive
st.set_page_config(page_title="IA Élections CI 2025", layout="wide")
st.title("🗳️ Assistant IA - Élections CI 2025")
st.subheader("Niveau 3 : Interaction, SQL Précis et Graphiques")

# --- BARRE LATÉRALE ---
st.sidebar.header("🔑 Authentification")
api_key = st.sidebar.text_input("Clé API OpenAI", type="password") # l'utilisateur doit entrer sa clé openai

# Fonction pour empêcher les injections SQL dangereuses
def validate_sql(query):
    """Vérifie si la requête SQL ne contient pas de mots-clés dangereux."""
    forbidden = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE"]
    for word in forbidden:
        if word in query.upper():
            return False, f"⚠️ Action interdite détectée : {word}"
    return True, query

# --- LOGIQUE PRINCIPALE ---

if api_key: # si la clé est OK on démarre
    try:
        router = HybridRouter(api_key) # le routeur est le cerveau de l'app, il décide quelle chémin prendre en fonction de la question
        llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key) # le modèle de langage
        db_path = "data/elections_ci.db" # chemin vers la base de données DuckDB contenant les résultats électoraux

        # 1. AFFICHAGE DE L'HISTORIQUE
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if "data" in message:
                    st.dataframe(message["data"])
                if "chart" in message:
                    st.bar_chart(message["chart"])

        # 2. GESTION DE LA SAISIE
        user_input = st.chat_input("Posez votre question (ex: Qui a gagné à Marcory ?)")
        
        current_query = user_input
        # Si on revient d'un bouton de clarification
        if not user_input and "final_query" in st.session_state:
            current_query = st.session_state.pop("final_query")

        if current_query:
            if user_input:
                st.session_state.messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)

            # --- ÉTAPE A : NORMALISATION ---
            clean_question = router.normalize_query(current_query) # Nettoie la question 
            
            # --- BLOC DÉSAMBIGUÏSATION (Boutons) ---
            if st.session_state.get("pending_clarification"):
                with st.chat_message("assistant"):
                    st.write("🤔 J'ai un doute sur la localité. Laquelle choisissez-vous ?")
                    cols = st.columns(min(len(st.session_state.options), 3))
                    for i, option in enumerate(st.session_state.options):
                        if cols[i % 3].button(option, key=f"btn_{i}"):
                            st.session_state.pending_clarification = False
                            # On force une question explicite pour la mémoire
                            st.session_state.final_query = f"Donne moi les résultats pour {option}"
                            st.rerun()
                st.stop()

            # --- ÉTAPE B : CLASSIFICATION ---
            intent = router.classify_intent(clean_question) # GPT décide de
            with st.chat_message("assistant"):
                response_content = ""
                df_to_save = None
                chart_to_save = None

                if intent == "GREETING":
                    response_content = "Bonjour ! Je suis votre analyste expert. Comment puis-je vous aider ?"
                    st.markdown(response_content)
                
                elif intent == "CLARIFY":
                    response_content = "Je serais ravi de vous aider ! Mais de quelle localité (commune, région) parlez-vous ?"
                    st.markdown(response_content)

                elif intent == "SQL":
                    status = st.status("🔍 Analyse statistique en cours...", state="running")
                    
                    # PROMPT SQL ULTRA-STRICT AVEC SCHÉMA
                    prompt_sql = f"""Tu es un expert SQL DuckDB.
                    SCHÉMA DES TABLES :
                    - circonscriptions (nom_circ, nom_region, nb_inscrits)
                    - resultats (nom_candidat, nom_parti, voix_obtenues, est_elu)
                    RÈGLES CRITIQUES :
                    1. Pour les noms de lieux, utilise TOUJOURS 'UPPER' et 'LIKE' (ex: nom_circ UPPER(nom_circ) LIKE '%YOPOUGON%').
                    2. Pour les statistiques par parti, utilise : SUM(voix_obtenues).
                    3. Ne réponds QUE par la requête SQL brute, sans texte autour.
                    Question : {clean_question}"""
                    
                    sql_raw = llm.invoke(prompt_sql).content
                    sql_clean = re.sub(r"```sql|```", "", sql_raw).strip()
                    
                    is_safe, final_sql = validate_sql(sql_clean)
                    if is_safe:
                        try:
                            with duckdb.connect(db_path) as conn:
                                df_result = conn.execute(final_sql).df()
                            
                            if not df_result.empty:
                                st.dataframe(df_result, use_container_width=True)
                                df_to_save = df_result
                                
                                # LOGIQUE GRAPHIQUE
                                if any(w in clean_question.lower() for w in ["graphique", "graphe", "visualise"]):
                                    num_cols = df_result.select_dtypes(include=['number']).columns.tolist()
                                    txt_cols = df_result.select_dtypes(include=['object']).columns.tolist()
                                    if num_cols and txt_cols:
                                        chart_to_save = df_result.set_index(txt_cols[0])[num_cols[0]]
                                        st.bar_chart(chart_to_save)

                                # INTERPRÉTATION HUMAINE
                                interp = llm.invoke(f"Analyse ces résultats électoraux brièvement : {df_result.to_string()}").content
                                response_content = interp
                                st.markdown(response_content)
                            else:
                                response_content = "Aucune donnée trouvée pour cette requête."
                                st.info(response_content)
                            status.update(label="✅ Analyse terminée", state="complete")
                        except Exception as e:
                            status.update(label="❌ Erreur SQL", state="error")
                            response_content = f"Désolé, je n'ai pas pu générer les stats (Erreur technique)."
                    else:
                        response_content = is_safe
                        st.error(response_content)

                else: # MOTEUR RAG
                    status = st.status("📖 Recherche documentaire...", state="running")
                    answer = router.run_rag_search(clean_question, history=st.session_state.messages[-3:])
                    st.markdown(answer)
                    response_content = answer
                    status.update(label="✅ Recherche terminée", state="complete")
                
                # 4. SAUVEGARDE FINALE
                if response_content:
                    new_msg = {"role": "assistant", "content": response_content}
                    if df_to_save is not None: new_msg["data"] = df_to_save
                    if chart_to_save is not None: new_msg["chart"] = chart_to_save
                    st.session_state.messages.append(new_msg)

    except Exception as e:
        st.error(f"Une erreur est survenue : {e}")
else:
    st.info("👋 Bonjour ! Entrez votre clé API OpenAI pour commencer l'analyse.")