"""
-Charger un dataset de questions
-Faire répondre ton IA à chaque question
-Comparer avec la bonne réponse
-Calculer des scores (précision, latence, sécurité)
-Envoyer les résultats dans Langfuse (dashboard)
"""

import os
import re
import time
import uuid
from dotenv import load_dotenv
from langfuse import Langfuse
from langchain_openai import ChatOpenAI
from scripts.router import HybridRouter
from scripts.prompts import SQL_SYSTEM_PROMPT, FINAL_ANSWER_PROMPT

load_dotenv()

# ── INITIALISATION - Connexion à Langfuse
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)
# chargement de mon router et de mon LLM
api_key = os.getenv("OPENAI_API_KEY")
router  = HybridRouter(api_key=api_key)
llm     = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=api_key)

# ── DATASET ─
DATASET_NAME = "Elections_CI_Benchmark"
try:
    dataset = langfuse.get_dataset(DATASET_NAME) # chargement du dataset
    print(f"📦 Dataset chargé : {DATASET_NAME} ({len(dataset.items)} items)") # si ça marche affiche le nom et le nombre de question
except Exception as e:
    print(f"❌ {e}"); exit(1)

run_name = f"Test_Fidelite_{int(time.time())}"
print(f"🚀 Lancement : {run_name}\n")

stats = {"correct": 0, "incorrect": 0, "erreur": 0, "skip": 0}


# ── SCORE D'EXACTITUDE ────────────────────────────────────────────────────────
def calculer_score(response: str, expected) -> tuple[float, str]: # elle compare la réponse de l'IA et bonne réponse attendue 
    if not expected or str(expected).strip() in ("", "None", "nan"): # si pas de réponse, vide, ou ou None on ignore la question.. Résultat (-1.0)
        return -1.0, "Pas de valeur attendue"
    # On met tout en minuscule    
    r = response.lower()
    e = str(expected).lower().strip()
    #Si la réponse attendue est dans la réponse IA alors résultat score = 1.0
    if e in r:
        return 1.0, f"Exact : '{expected}'"

    mots  = e.split() # on découpe la réponse attendu en mot
    ratio = sum(1 for m in mots if m in r) / len(mots) if mots else 0
    if ratio >= 0.8: return 0.8, f"Fort ({ratio:.0%})"
    if ratio >= 0.5: return 0.5, f"Partiel ({ratio:.0%})"
    return 0.0, f"Aucun (attendu: '{expected}')"


# ── GÉNÉRATION RÉPONSE ────────────────────────────────────────────────────────
def generer_reponse(question: str) -> tuple[str, str]:
    mots_interdits = ["drop","delete","insert","update","alter",
                      "mot de passe","password","secret"]
    if any(m in question.lower() for m in mots_interdits):
        return "⚠️ Requête refusée par les guardrails.", "BLOCKED"

    intent = router.classify_intent(question)

    if intent == "SQL":
        prompt    = f"{SQL_SYSTEM_PROMPT}\n\nQuestion : {question}"
        sql_raw   = llm.invoke(prompt).content
        match     = re.search(r"(SELECT|WITH).*?;", sql_raw, re.DOTALL|re.IGNORECASE)
        sql_clean = re.sub(r"```sql|```", "",
                           match.group(0) if match else sql_raw).strip()
        result    = router.executer_sql(sql_clean)
        if result.success and not result.data.empty:
            analyse = (f"{FINAL_ANSWER_PROMPT}\nQuestion: {question}\n"
                       f"Données:\n{result.data.to_string(index=False)}")
            return llm.invoke(analyse).content, "SQL"
        return "Aucun résultat trouvé.", "SQL"

    return router.run_rag_search(question), "RAG"


# ── BOUCLE PRINCIPALE ─────────────────────────────────────────────────────────
for i, item in enumerate(dataset.items, start=1):
    question = (
        item.input if isinstance(item.input, str)
        else item.input.get("question", str(item.input))
    )
    print(f"[{i:03d}/{len(dataset.items):03d}] ❓ {question[:70]}")

    try:
        t0 = time.time()
        reponse, intent = generer_reponse(question)
        latence_ms = round((time.time() - t0) * 1000, 1)

        # ── Créer la trace via API REST ───────────────────────────────
        trace_id = str(uuid.uuid4())
        try:
            langfuse.api.trace.create(request={
                "id":       trace_id,
                "name":     "benchmark_query",
                "input":    {"question": question},
                "output":   {"response": reponse, "intent": intent},
                "metadata": {"run": run_name, "latence_ms": latence_ms},
                "tags":     ["benchmark", run_name],
            })
        except Exception as e_trace:
            # Si la création de trace échoue, on continue sans trace
            print(f"        ℹ️  Trace non créée ({e_trace})")
            trace_id = None

        # ── Lier l'item au run ────────────────────────────────────────
        # En v4, item.link(run_name, observation_id=trace_id)
        # observation_id = ID de la trace créée ci-dessus
        if trace_id:
            try:
                item.link(run_name, observation_id=trace_id)
            except TypeError:
                try:
                    item.link(run_name, trace_id)   # positional
                except TypeError:
                    item.link(run_name)              # sans trace_id

        # ── Score ─────────────────────────────────────────────────────
        score_val, commentaire = calculer_score(reponse, item.expected_output)

        if score_val < 0:
            stats["skip"] += 1
            print(f"        ⏭️  Skippé : {commentaire}")
            continue

        if trace_id:
            # Score exactitude
            try:
                langfuse.api.score.create(request={
                    "traceId":  trace_id,
                    "name":     "exactitude_donnees",
                    "value":    score_val,
                    "comment":  commentaire,
                    "dataType": "NUMERIC",
                })
            except Exception:
                pass

            # Score latence
            s_lat = max(0.0, min(1.0, 1.0 - (latence_ms - 2000) / 8000))
            try:
                langfuse.api.score.create(request={
                    "traceId":  trace_id,
                    "name":     "latence",
                    "value":    round(s_lat, 2),
                    "comment":  f"{latence_ms} ms",
                    "dataType": "NUMERIC",
                })
            except Exception:
                pass

            # Score guardrail
            if intent == "BLOCKED":
                try:
                    langfuse.api.score.create(request={
                        "traceId":  trace_id,
                        "name":     "securite_guardrail",
                        "value":    1.0,
                        "comment":  "Injection bloquée",
                        "dataType": "NUMERIC",
                    })
                except Exception:
                    pass

        icone = "✅" if score_val >= 0.8 else ("⚠️ " if score_val >= 0.5 else "❌")
        print(f"        {icone} score={score_val:.1f} | {commentaire[:50]} | {latence_ms}ms")

        if score_val >= 0.8: stats["correct"]   += 1
        else:                 stats["incorrect"] += 1

    except Exception as e:
        print(f"        ⚠️  Erreur : {e}")
        stats["erreur"] += 1

# ── FLUSH ─────────────────────────────────────────────────────────────────────
langfuse.flush()

total_eval = stats["correct"] + stats["incorrect"]
precision  = stats["correct"] / total_eval if total_eval > 0 else 0

print(f"""
{'='*55}
  📊 RAPPORT — {run_name}
{'='*55}
  Total items      : {len(dataset.items)}
  ✅ Corrects       : {stats['correct']}
  ❌ Incorrects     : {stats['incorrect']}
  ⏭️  Sans expected  : {stats['skip']}
  ⚠️  Erreurs        : {stats['erreur']}
  🎯 Précision      : {precision:.1%}
  Dashboard → {DATASET_NAME} → {run_name}
{'='*55}
""")