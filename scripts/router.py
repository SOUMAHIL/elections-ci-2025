import os
import json
import re
from difflib import get_close_matches
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
 
 
class HybridRouter:
    """Routeur hybride SQL/RAG pour l'assistant électoral."""
 
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.llm = ChatOpenAI(
            model="gpt-4o", temperature=0, openai_api_key=api_key
        )
 
        # Chargement du dictionnaire des entités
        dict_path = "data/election_dict.json"
        if os.path.exists(dict_path):
            with open(dict_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.regions = d.get("regions", [])
            self.circs   = d.get("circonscriptions", [])
            self.partis  = d.get("partis", [])
        else:
            self.regions = self.circs = self.partis = []
 
        self._referentiel = [
            x for x in (self.regions + self.circs + self.partis) if x
        ]
 
        # Chargement du vector store FAISS (optionnel)
        self.vector_store = None
        faiss_path = "data/faiss_index"
        if os.path.exists(faiss_path):
            try:
                embeddings = OpenAIEmbeddings(openai_api_key=api_key)
                self.vector_store = FAISS.load_local(
                    faiss_path, embeddings,
                    allow_dangerous_deserialization=True
                )
            except Exception:
                pass
 
    # ── NORMALISATION ──────────────────────────────────────────────────
    def normalize_query(self, query: str) -> str:
        """Détecte les entités ambiguës et met à jour st.session_state."""
        import streamlit as st
 
        blacklist = {"commune", "sous-préfecture", "le", "la", "les",
                     "score", "candidat", "voix", "météo"}
 
        clean   = re.sub(r"[^\w\s]", " ", query)
        words   = clean.split()
        matches = []
 
        for word in words:
            w = word.lower().strip()
            if len(w) <= 3 or w in blacklist:
                continue
            hits = [r for r in self._referentiel if w in r.lower()]
            matches.extend(hits)
 
        matches = list(dict.fromkeys(matches))
        circs_matchees = [m for m in matches if m in self.circs]
 
        if len(circs_matchees) > 3:
            st.session_state.pending_clarification = True
            st.session_state.options = circs_matchees[:6]
            return query
 
        for match in matches:
            if match.lower() in query.lower():
                st.session_state.pending_clarification = False
                return match
 
        return query
 
    # ── CLASSIFICATION ─────────────────────────────────────────────────
    def classify_intent(self, query: str, callbacks=None) -> str:
        """Classifie l'intention : SQL, RAG, CLARIFY, GREETING."""
        prompt = f"""Tu es l'aiguilleur d'une application électorale.
Réponds par UN SEUL MOT parmi : GREETING, CLARIFY, SQL, RAG.
- GREETING : salutation
- SQL      : stats, scores, gagnants, participation, top, combien
- CLARIFY  : lieu non précisé
- RAG      : description, contexte, narratif
 
Question : {query}
Réponse :"""
 
        kwargs = {}
        if callbacks:
            kwargs["config"] = {"callbacks": callbacks}
 
        response = self.llm.invoke(prompt, **kwargs).content.strip().upper()
 
        for intent in ["GREETING", "SQL", "CLARIFY", "RAG"]:
            if intent in response:
                return intent
        return "RAG"
 
    # ── RAG SEARCH ─────────────────────────────────────────────────────
    def run_rag_search(self, query: str, history=None, callbacks=None) -> str:
        """Recherche RAG dans l'index FAISS."""
        if self.vector_store is None:
            return (
                "L'index vectoriel n'est pas disponible. "
                "Lance create_embeddings.py pour l'initialiser."
            )
 
        docs    = self.vector_store.similarity_search(query, k=5)
        context = "\n".join([d.page_content for d in docs])
 
        hist_text = ""
        if history:
            for msg in history[-3:]:
                role = "Utilisateur" if msg["role"] == "user" else "Assistant"
                hist_text += f"{role}: {msg['content']}\n"
 
        prompt = f"""Tu es un analyste électoral expert.
Réponds UNIQUEMENT à partir du contexte fourni.
Si la réponse n'est pas dans le contexte, dis :
"Non trouvé dans le PDF fourni."
 
Contexte   : {context}
Historique : {hist_text}
Question   : {query}"""
 
        kwargs = {}
        if callbacks:
            kwargs["config"] = {"callbacks": callbacks}
 
        return self.llm.invoke(prompt, **kwargs).content
 
    # ── SQL EXECUTION ──────────────────────────────────────────────────
    def executer_sql(self, sql: str):
        """Exécute une requête SQL sur la base DuckDB."""
        import duckdb
        import pandas as pd
 
        class SQLResult:
            def __init__(self, success, data=None, error=""):
                self.success = success
                self.data    = data
                self.error   = error
 
        # Guardrail
        forbidden = ["DROP", "DELETE", "INSERT", "UPDATE",
                     "ALTER", "TRUNCATE", "CREATE"]
        for word in forbidden:
            if re.search(r'\b' + word + r'\b', sql.upper()):
                return SQLResult(False, error=f"Opération interdite : {word}")
 
        # LIMIT auto
        if "LIMIT" not in sql.upper():
            sql = re.sub(r";?\s*$", "", sql.strip()) + " LIMIT 100;"
 
        try:
            with duckdb.connect("data/elections_ci.db") as conn:
                df = conn.execute(sql).df()
            return SQLResult(True, data=df)
        except Exception as e:
            return SQLResult(False, error=str(e))
 