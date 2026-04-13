import os
import json
import streamlit as st
import re
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from thefuzz import process, fuzz

class HybridRouter:
    def __init__(self, api_key):
        self.api_key = api_key
        dict_path = "data/election_dict.json"
        if os.path.exists(dict_path):
            with open(dict_path, "r", encoding="utf-8") as f:
                self.dictionary = json.load(f)
        else:
            self.dictionary = {"regions": [], "circonscriptions": [], "partis": []}

        self.llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)
        embeddings = OpenAIEmbeddings(openai_api_key=api_key)
        self.vector_store = FAISS.load_local(
            "data/faiss_index", 
            embeddings, 
            allow_dangerous_deserialization=True
        )

    def normalize_query(self, query):
        clean_text = re.sub(r'[^\w\s]', '', query)
        words = clean_text.split()
        referentiel = self.dictionary["regions"] + self.dictionary["circonscriptions"] + self.dictionary["partis"]
        
        for word in words:
            if len(word) > 3:
                # On cherche les correspondances
                potential_matches = [r for r in referentiel if word.lower() in r.lower()]
                
                # --- NOUVEAUTÉ : Vérification d'unicité ---
                # Si le mot tapé correspond EXACTEMENT à une option, on ne demande pas
                exact_match = [r for r in potential_matches if word.lower() == r.lower()]
                
                if exact_match:
                    query = query.replace(word, exact_match[0])
                    continue # On passe au mot suivant sans déclencher les boutons

                if len(potential_matches) > 1:
                    st.session_state.pending_clarification = True
                    st.session_state.options = list(set(potential_matches))
                    return query
        return query
    
    def classify_intent(self, query):
        prompt = f"""Tu es l'aiguilleur d'une application électorale de haute précision.
        Réponds par UN SEUL MOT :
        - GREETING : Politesse, bonjour, salut.
        - CLARIFY : L'utilisateur demande un gagnant ou un score sans préciser de lieu (ex: "Qui gagne ?", "Donne moi le score").
        - SQL : TOUTE question demandant un calcul (Somme, Top 3, Top 5, classement, total de voix, pourcentage). C'est CRITIQUE pour la précision.
        - RAG : Questions narratives sur un candidat, un slogan, ou un lieu spécifique déjà nommé pour une description.
        
        Question : {query}
        Réponse :"""
        
        response = self.llm.invoke(prompt).content.strip().upper()
        if "GREETING" in response: return "GREETING"
        if "CLARIFY" in response: return "CLARIFY"
        if "SQL" in response: return "SQL"
        return "RAG"
    
    def run_rag_search(self, query, history=[]):
        docs = self.vector_store.similarity_search(query, k=10)
        doc_context = "\n".join([d.page_content for d in docs])
        chat_history = ""
        for msg in history[-3:]:
            role = "Utilisateur" if msg["role"] == "user" else "Assistant"
            chat_history += f"{role}: {msg['content']}\n"
        
        prompt = f"""Tu es l'Analyste IA Expert des Élections 2025.
        Réponds en utilisant le CONTEXTE TECHNIQUE et l'HISTORIQUE.
        Si la réponse n'est pas dans le contexte, dis-le poliment.

        HISTORIQUE :
        {chat_history}
        CONTEXTE TECHNIQUE :
        {doc_context}
        QUESTION : {query}"""
        return self.llm.invoke(prompt).content