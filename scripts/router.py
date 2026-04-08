import os
import json # Pour lire le dictionnaire de normalisation
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from thefuzz import process # Bibliothèque pour la comparaison de texte floue (Fuzzy Matching)
from thefuzz import fuzz
class HybridRouter:
    """
    Classe responsable de l'aiguillage des questions utilisateurs.
    Elle normalise les entités (villes, partis) et choisit entre SQL et RAG.
    """
    def __init__(self, api_key):
        self.api_key = api_key
        
        # --- CHARGEMENT DU RÉFÉRENTIEL ---
        # On charge le dictionnaire créé par build_dictionary.py pour l'Entity Resolution
        dict_path = "data/election_dict.json"
        if os.path.exists(dict_path):
            with open(dict_path, "r", encoding="utf-8") as f:
                self.dictionary = json.load(f)
        else:
            # Sécurité si le fichier n'existe pas encore
            self.dictionary = {"regions": [], "circonscriptions": [], "partis": []}

        # --- INITIALISATION DES MOTEURS IA ---
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)
        
        # Chargement de la base vectorielle (Mémoire sémantique pour le RAG)
        embeddings = OpenAIEmbeddings(openai_api_key=api_key)
        self.vector_store = FAISS.load_local(
            "data/faiss_index", 
            embeddings, 
            allow_dangerous_deserialization=True
        )

    def normalize_query(self, query):
        """
        Version Token Set : La plus robuste pour les noms à rallonge.
        """
        new_query = query
        # On récupère le dictionnaire
        referentiel = self.dictionary["regions"] + self.dictionary["circonscriptions"] + self.dictionary["partis"]
    
        # On nettoie la ponctuation
        words = query.replace("?", "").replace("!", "").split()
        for word in words:
            if len(word) > 3:
               best_match = None
               highest_score = 0
               
               for item in referentiel:
                   # token_set_ratio ignore l'ordre des mots et les répétitions
                   # C'est parfait pour trouver "sifié" dans "205 - KAMALO, SIFIE ET WOROFLA..."
                   score = fuzz.token_set_ratio(word.lower(), item.lower())
                   
                   if score > highest_score:
                     highest_score = score
                     best_match = item
                
               # ON BAISSE LE SEUIL À 75 POUR PLUS DE SOUPLESSE
               if highest_score > 75: 
                   new_query = new_query.replace(word, best_match)
                   print(f"✨ MATCH TROUVÉ : '{word}' -> '{best_match}' (Score: {highest_score})")
               else:
                   print(f"❌ SCORE TROP BAS : '{word}' vs '{best_match}' (Score: {highest_score})")
                   
        return new_query          
    
    def classify_intent(self, query):
        """
        Utilise le LLM pour décider si la question nécessite un calcul (SQL) 
        ou une explication textuelle (RAG).
        """
        prompt = f"""Analyse la question de l'utilisateur. Réponds par 'SQL' ou 'RAG'.
        - SQL : Si la question demande un calcul, un total, une moyenne, un classement ou un graphique.
        - RAG : Si la question porte sur un nom propre, une recherche de gagnant localisée ou une explication.
        
        Question : {query}"""
        
        response = self.llm.invoke(prompt).content.strip().upper()
        # On force le retour en majuscules pour éviter les erreurs de comparaison
        return "SQL" if "SQL" in response else "RAG"

    def run_rag_search(self, query):
        """
        Exécute une recherche sémantique dans les documents indexés.
        Idéal pour les questions narratives ou les recherches de noms spécifiques.
        """
        # Récupère les 10 passages les plus proches (k=10 pour plus de robustesse)
        docs = self.vector_store.similarity_search(query, k=10)
        context = "\n".join([d.page_content for d in docs])
        
        prompt = f"""Tu es l'Analyste IA des élections 2025. Réponds en utilisant UNIQUEMENT le contexte fourni.
        Si l'utilisateur a fait une légère erreur sur un nom, utilise l'information la plus cohérente.
        
        CONTEXTE :
        {context}
        
        QUESTION : {query}"""
        
        return self.llm.invoke(prompt).content