import time
import streamlit as st
import duckdb
import re
import os
from rapidfuzz import process, fuzz
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langfuse.langchain import CallbackHandler

from scripts.router import HybridRouter, SYNONYMES
from scripts.prompts import (
    SQL_SYSTEM_PROMPT, FINAL_ANSWER_PROMPT,
    CLARIFICATION_PROMPT, GUARDRAIL_RESPONSE, detecter_injection,
)

load_dotenv()

try:
    for key in ['MISTRAL_API_KEY','LANGFUSE_PUBLIC_KEY',
                'LANGFUSE_SECRET_KEY','LANGFUSE_HOST']:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass

st.set_page_config(
    page_title="IA Élections CI 2025",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { background: #FAFAFA !important; border-right: 0.5px solid #E8E7E0; }
[data-testid="stMetric"] {
    background: #F3F2EC !important; border-radius: 10px !important;
    padding: 10px 14px !important; border: 0.5px solid #E0DFD8 !important;
}
[data-testid="stMetricLabel"]  { font-size: 11px !important; color: #888 !important; }
[data-testid="stMetricValue"]  { font-size: 22px !important; font-weight: 500 !important; }
[data-testid="stChatMessage"] {
    border-radius: 12px !important; border: 0.5px solid #EBEBEB !important;
    padding: 12px 16px !important; margin-bottom: 4px !important;
}
[data-testid="stChatInput"] textarea {
    border-radius: 24px !important; background: #F5F4EE !important;
    border: 0.5px solid #D4D3CC !important; font-size: 14px !important;
    padding: 12px 18px !important;
}
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "data/elections_ci.db"

# ── SESSION STATE ──────────────────────────────────────────────────────────────
for k, v in [("messages", []), ("pending_clarification", False),
              ("options", []), ("session_id", f"web-{int(time.time())}"),
              ("suggestion_db", None)]:
    if k not in st.session_state:
        st.session_state[k] = v


# ── CACHE MÉTRIQUES SIDEBAR uniquement ───────────────────────────────────────
# Seul @st.cache_data est utilisé — pour les données simples (nombres).
# @st.cache_resource est retiré sur router et llm car il causait des crashs
# sur Streamlit Cloud avec les objets complexes (HybridRouter, FAISS).
@st.cache_data
def get_metriques_sidebar() -> tuple:
    try:
        with duckdb.connect(DB_PATH) as c:
            nb_circs     = c.execute("SELECT COUNT(DISTINCT code_circ) FROM circonscriptions").fetchone()[0]
            nb_candidats = c.execute("SELECT COUNT(*) FROM resultats").fetchone()[0]
            taux_moy     = c.execute(
                "SELECT ROUND(AVG(nb_votants*100.0/NULLIF(nb_inscrits,0)),1) FROM circonscriptions"
            ).fetchone()[0]
        return nb_circs, nb_candidats, taux_moy
    except Exception:
        return 205, "—", "—"


# ── FONCTION SUGGESTION RAPIDFUZZ ─────────────────────────────────────────────
def suggerer_avec_rapidfuzz(query: str, router=None) -> str | None:
    q = query.lower()

    for alias in SYNONYMES.keys():
        if alias in q:
            return None

    mots_circs = router.mots_circs if router else []
    for mot in mots_circs:
        if mot in q:
            return None

    mots_question = [re.sub(r'[^a-zA-ZÀ-ÿ]', '', m) for m in q.split() if len(m) >= 5]
    mots_question = [m for m in mots_question if len(m) >= 5]

    for mot in mots_question:
        result = process.extractOne(
            mot, mots_circs,
            scorer=fuzz.ratio, score_cutoff=75
        )
        if result and result[0] != mot:
            return result[0]

    return None


# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗳️ Élections CI 2025")
    st.caption("CEI — Scrutin 27 Décembre 2025")
    st.divider()

    nb_circs, nb_candidats, taux_moy = get_metriques_sidebar()

    col1, col2 = st.columns(2)
    col1.metric("Circonscriptions", nb_circs)
    col2.metric("Candidats", f"{nb_candidats:,}".replace(",", " ") if isinstance(nb_candidats, int) else nb_candidats)
    st.metric("Taux de participation moyen", f"{taux_moy}%" if taux_moy != "—" else "—")
    st.divider()

    st.markdown("**Résultats par parti**")
    st.markdown("""
<div style="display:flex;flex-direction:column;gap:5px;margin-top:6px;font-size:12px">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#E85D04;flex-shrink:0"></div><span>RHDP</span>
    </div><span style="font-weight:600;color:#E85D04">155 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#1D6FA4;flex-shrink:0"></div><span>PDCI-RDA</span>
    </div><span style="font-weight:600;color:#1D6FA4">25 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#7B5EA7;flex-shrink:0"></div><span>Indépendants</span>
    </div><span style="font-weight:600;color:#7B5EA7">22 sièges</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#2D9A27;flex-shrink:0"></div><span>FPI</span>
    </div><span style="font-weight:600;color:#2D9A27">1 siège</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#C77D29;flex-shrink:0"></div><span>LE BUFFLE</span>
    </div><span style="font-weight:600;color:#C77D29">1 siège</span>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
    <div style="display:flex;align-items:center;gap:6px">
      <div style="width:10px;height:10px;border-radius:50%;background:#888888;flex-shrink:0"></div><span>UNPR</span>
    </div><span style="font-weight:600;color:#888">1 siège</span>
  </div>
  <div style="margin-top:4px;font-size:11px;color:#999">Autres : ADCI, CODE, MGC, GP-PAIX, EDS et 30+ autres</div>
</div>
""", unsafe_allow_html=True)

    st.divider()
    api_key = st.secrets.get("MISTRAL_API_KEY", "") or os.getenv("MISTRAL_API_KEY", "")
    if not api_key:
        api_key = st.text_input("🔑 Clé API Mistral", type="password", placeholder="sk-...")
    if not api_key:
        st.warning("⚠️ Entrez votre clé API Mistral.")
        st.stop()

    if st.button("🗑️ Effacer la conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.suggestion_db = None
        st.rerun()

# ── HEADER ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:14px;margin-bottom:4px">
  <div style="font-size:28px">🗳️</div>
  <div>
    <h2 style="margin:0;font-size:22px;font-weight:500">Assistant IA — Élections CI 2025</h2>
    <p style="margin:0;font-size:13px;color:#888">Source : PDF officiel CEI · Scrutin du 27 décembre 2025</p>
  </div>
</div>
""", unsafe_allow_html=True)
st.divider()


# ── UTILITAIRES ────────────────────────────────────────────────────────────────
def validate_sql(sql):
    return not any(w in sql.upper() for w in
                   ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"])

def construire_historique_ctx(messages, nb_echanges=3):
    if not messages:
        return ""
    msgs_recents = messages[-(nb_echanges * 2):]
    ctx = ""
    for msg in msgs_recents:
        if msg["role"] == "user":
            ctx += f"Utilisateur: {msg['content'][:200]}\n"
        else:
            contenu = msg.get("content", "")[:200] if msg.get("content") else ""
            if contenu:
                ctx += f"Assistant: {contenu}\n"
    return ctx.strip()

def llm_call_with_retry(llm, langfuse_handler, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            return llm.invoke(prompt, config={"callbacks": [langfuse_handler]}).content
        except Exception as e:
            msg_e = str(e)
            if "429" in msg_e or "rate_limit" in msg_e.lower():
                wait = (attempt + 1) * 2
                st.warning(f"⏳ Limite API atteinte, nouvelle tentative dans {wait}s…")
                time.sleep(wait)
            elif "503" in msg_e or "timeout" in msg_e.lower() or "ReadTimeout" in msg_e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise Exception("⚠️ Le service IA est temporairement indisponible. Réessayez dans quelques minutes.")
            else:
                raise
    raise Exception("Rate limit persistant après 3 tentatives.")


# ── GRAPHIQUES PLOTLY ─────────────────────────────────────────────────────────
def generer_graphique(df, question: str):
    try:
        import plotly.graph_objects as go
        q        = question.lower()
        num_cols = [c for c in df.columns if df[c].dtype in ["int64","float64","int32","float32"]]
        str_cols = [c for c in df.columns if df[c].dtype == "object"]
        if not num_cols:
            return None
        y_col = (next((c for c in num_cols if "voix" in c.lower()), None)
                 or next((c for c in num_cols if "pct" in c.lower() or "taux" in c.lower()), None)
                 or num_cols[0])
        x_col = str_cols[0] if str_cols else df.columns[0]
        values = df[y_col].values
        if len(values) == 0:
            return None
        COULEURS_PARTIS = {
            "RHDP": "#E85D04", "PDCI": "#1D6FA4", "FPI": "#2D9A27",
            "INDEPENDANT": "#7B5EA7", "ADCI": "#C77D29", "CODE": "#6B7280",
            "MGC": "#D4A017", "EDS": "#4682B4", "GP-PAIX": "#20B2AA",
            "LE BUFFLE": "#8B4513", "UNPR": "#4B0082",
        }
        def get_couleur(label):
            l = str(label).upper()
            for parti, col in COULEURS_PARTIS.items():
                if parti in l: return col
            return None
        def clean_label(s, maxlen=28):
            s = str(s).strip()
            slogans = ["UNE COTE DIVOIRE EN PAIX", "TOUS ENSEMBLE POUR",
                       "UNE CÔTE D'IVOIRE", "OSONS LE CHANGEMENT",
                       "ENSEMBLE POUR LE", "POUR LA NATION"]
            s_up = s.upper()
            for sl in slogans:
                if sl in s_up:
                    idx = s_up.index(sl)
                    prefix = s[:idx].strip(" ,()-")
                    if len(prefix) >= 3: return prefix[:maxlen]
            return s[:maxlen] if len(s) > maxlen else s
        parti_col = next((c for c in str_cols if "parti" in c.lower()), None)
        labels = [clean_label(v) for v in df[x_col]]
        couleurs = []
        for i, row in df.iterrows():
            parti_val = str(row.get(parti_col, "")) if parti_col else ""
            c = get_couleur(parti_val) or get_couleur(str(row.get(x_col, "")))
            couleurs.append(c or "#64748B")
        def titre_intelligent(q):
            q = re.sub(r'(?i)donne[- ]?moi\s+', '', q)
            q = re.sub(r'(?i)\s+et\s+(génère[- ]?moi\s+)?(un\s+)?(graphique|chart|diagramme)\w*\s*[?!]*$', '', q)
            q = re.sub(r'[?!]+$', '', q).strip()
            q = re.sub(r'\s+', ' ', q).strip()
            if q and q[0].islower(): q = q[0].upper() + q[1:]
            return q[:80]
        titre = titre_intelligent(question)
        est_taux = any(w in q for w in ["taux","participation","pourcentage","%"]) or "taux" in y_col.lower()
        est_top  = any(w in q for w in ["top","classement","plus de voix","rang","premier"])
        est_vert = est_taux or (len(df) <= 5 and not est_top)
        hover_fmt = [f"<b>{l}</b><br>Taux : {v:.2f}%" if est_taux
                     else f"<b>{l}</b><br>Voix : {int(v):,}".replace(",", "\u202f")
                     for l, v in zip(labels, values)]
        layout = dict(
            title=dict(text=f"<b>{titre}</b>", font=dict(size=16, color="#1a1a2e", family="Arial"),
                       x=0, xanchor="left", pad=dict(l=10)),
            paper_bgcolor="rgba(250,250,250,1)", plot_bgcolor="rgba(245,244,238,1)",
            font=dict(family="Arial", size=12, color="#444"),
            margin=dict(l=20, r=20, t=60, b=60), showlegend=False,
            annotations=[dict(text="Source : CEI — Élections législatives CI, 27 déc. 2025",
                              xref="paper", yref="paper", x=0, y=-0.12,
                              showarrow=False, font=dict(size=10, color="#aaa"), align="left")],
            hoverlabel=dict(bgcolor="white", bordercolor="#ddd", font=dict(size=12, color="#333")),
        )
        if not est_vert:
            li, vi, ci, hi = labels[::-1], list(values)[::-1], couleurs[::-1], hover_fmt[::-1]
            fig = go.Figure(go.Bar(
                x=vi, y=li, orientation="h",
                marker=dict(color=ci, line=dict(color="white", width=1.5), opacity=0.92),
                text=[f"{int(v):,}".replace(",", "\u202f") for v in vi],
                textposition="outside", textfont=dict(size=11, color="#333", family="Arial Bold"),
                hovertext=hi, hoverinfo="text",
            ))
            fig.update_layout(**layout, height=max(350, 60 + len(labels) * 42),
                xaxis=dict(title="Voix obtenues", gridcolor="#e5e7eb", showline=False, tickformat=",", color="#666"),
                yaxis=dict(gridcolor="rgba(0,0,0,0)", showline=False, tickfont=dict(size=11), color="#444"),
                bargap=0.25)
        else:
            text_vals = [f"{v:.1f}%" if est_taux else f"{int(v):,}".replace(",", "\u202f") for v in values]
            fig = go.Figure(go.Bar(
                x=list(range(len(labels))), y=list(values),
                marker=dict(color=couleurs, line=dict(color="white", width=1.5), opacity=0.92),
                text=text_vals, textposition="outside",
                textfont=dict(size=11, color="#333", family="Arial Bold"),
                hovertext=hover_fmt, hoverinfo="text",
            ))
            y_axis = dict(title="Taux (%)" if est_taux else "Voix",
                          gridcolor="#e5e7eb", showline=False, color="#666",
                          range=[0, max(values) * 1.2])
            if not est_taux: y_axis["tickformat"] = ","
            fig.update_layout(**layout, height=420,
                xaxis=dict(tickmode="array", tickvals=list(range(len(labels))), ticktext=labels,
                           tickangle=-30 if len(labels) > 3 else 0,
                           gridcolor="rgba(0,0,0,0)", showline=False, color="#444"),
                yaxis=y_axis, bargap=0.3)
        fig.update_layout(dragmode=False,
            modebar=dict(remove=["zoom","pan","select","lasso","zoomIn","zoomOut","autoScale","resetScale"]))
        return fig
    except Exception:
        import traceback; traceback.print_exc()
        return None


# ── SUGGESTIONS RAPIDES ────────────────────────────────────────────────────────
SUGGESTIONS = [
    ("🏆 Gagnant à Cocody",      "Qui a gagné à COCODY, COMMUNE dans le District d'Abidjan ?"),
    ("📊 Taux à Korhogo",        "Quel est le taux de participation à KORHOGO, VILLE ?"),
    ("🔝 Top 3 à Bouaké",        "Donne le top 3 des candidats à BOUAKE, VILLE avec graphique"),
    ("🗺️ Région Agneby-Tiassa", "Résultats dans la région AGNEBY-TIASSA ?"),
    ("📈 RHDP vs PDCI",          "Combien de sièges le PDCI-RDA a remporté ?"),
    ("❓ Qu'est-ce que la CEI ?","Qu'est-ce que la CEI ?"),
]

if not st.session_state.messages:
    st.markdown("""
<div style="background:#F5F4EE;border-radius:14px;padding:20px 24px;margin-bottom:16px;border:0.5px solid #E0DFD8">
  <p style="font-size:14px;font-weight:500;margin:0 0 6px">👋 Bienvenue sur l'Assistant IA des Élections CI 2025</p>
  <p style="font-size:13px;color:#666;margin:0">
    Posez vos questions sur les résultats, les candidats, les partis ou les taux de participation.
    Je peux aussi générer des <strong>graphiques interactifs</strong> — ajoutez simplement <em>«avec graphique»</em>.
  </p>
</div>
""", unsafe_allow_html=True)
    st.markdown("**Essayez par exemple :**")
    cols = st.columns(3)
    for i, (label, query) in enumerate(SUGGESTIONS):
        if cols[i % 3].button(label, use_container_width=True, key=f"sug_{i}"):
            st.session_state.messages.append({"role": "user", "content": query})
            st.session_state["final_query"] = query
            st.rerun()
    st.markdown("")

# ── HISTORIQUE ─────────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("data") is not None:
            st.dataframe(msg["data"])
        if msg.get("chart") is not None:
            st.plotly_chart(msg["chart"], use_container_width=True)

# ── SUGGESTION EN ATTENTE ─────────────────────────────────────────────────────
if st.session_state.suggestion_db:
    suggestion_en_attente = st.session_state.suggestion_db
    query_en_attente      = st.session_state.get("suggestion_query", "")
    st.warning(f"❓ Aucun résultat trouvé pour **\"{query_en_attente}\"**.")
    st.markdown(f"🔍 Vouliez-vous dire **{suggestion_en_attente}** ?")
    if st.button(f"✅ Oui, chercher pour : {suggestion_en_attente}", key="btn_suggestion"):
        st.session_state.suggestion_db    = None
        st.session_state.suggestion_query = None
        if "à" in query_en_attente.lower():
            parties    = query_en_attente.lower().split("à", 1)
            nouvelle_q = parties[0] + "à " + suggestion_en_attente + " ?"
        else:
            nouvelle_q = query_en_attente.rstrip("?") + f" à {suggestion_en_attente} ?"
        st.session_state["final_query"] = nouvelle_q
        st.rerun()
    st.stop()

# ── INPUT ──────────────────────────────────────────────────────────────────────
user_input    = st.chat_input("Posez votre question sur les élections CI 2025…")
current_query = user_input or st.session_state.pop("final_query", None)

if not current_query:
    st.stop()

# ── AFFICHER MESSAGE USER ─────────────────────────────────────────────────────
if user_input:
    st.session_state.suggestion_db = None
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

# ── TRAITEMENT ────────────────────────────────────────────────────────────────
t_global_start   = time.time()
langfuse_handler = CallbackHandler()
router           = HybridRouter(api_key)
llm              = ChatMistralAI(
    model="mistral-small-latest",
    temperature=0,
    mistral_api_key=api_key,
    timeout=30,
)

# ── SUGGESTION RAPIDFUZZ — AVANT Mistral ─────────────────────────────────────
if user_input:
    suggestion_pre = suggerer_avec_rapidfuzz(user_input, router=router)
    if suggestion_pre:
        st.session_state.suggestion_db    = suggestion_pre
        st.session_state.suggestion_query = user_input
        st.rerun()

route_result   = router.route(
    current_query,
    history=st.session_state.messages,
    callbacks=[langfuse_handler],
    session_id=st.session_state.get("session_id", "web"),
)
clean_question = route_result["clean_query"]
intent         = route_result["intent"]
trace_id       = route_result.get("trace_id")

veut_graphique = any(w in current_query.lower() for w in
                     ["graphique","graph","chart","visualis","courbe",
                      "diagramme","histogramme","pie","camembert"])

# ── RÉPONSE ────────────────────────────────────────────────────────────────────
response   = ""
df_save    = None
chart_save = None

with st.chat_message("assistant"):

    if intent == "BLOCKED":
        response = GUARDRAIL_RESPONSE
        st.warning(f"🛡️ {response}")

    elif intent == "GREETING":
        response = (
            "👋 **Bonjour !** Je suis l'assistant IA des élections ivoiriennes 2025.\n\n"
            "Je peux répondre à vos questions sur :\n"
            "- 🏆 Les **gagnants** par circonscription\n"
            "- 📊 Les **taux de participation**\n"
            "- 🎯 Les **scores** des candidats et partis\n"
            "- 📈 Des **graphiques interactifs** sur demande\n\n"
            "*Exemple : « Top 3 à Bouaké avec graphique »*"
        )
        st.markdown(response)

    elif intent == "AMBIGUOUS":
        response = route_result["response"]
        st.info(response)

    elif intent == "RAG":
        response = route_result["response"] or router.run_rag_search(
            clean_question,
            history=st.session_state.messages[-3:],
            callbacks=[langfuse_handler],
            trace_id=trace_id,
        )
        st.markdown(response)

    elif intent == "SQL":
        with st.spinner("🔍 Analyse en cours..."):
            try:
                t_sql_start    = time.time()
                historique_ctx = construire_historique_ctx(st.session_state.messages)
                prompt_sql     = f"{SQL_SYSTEM_PROMPT}\n\n"
                if historique_ctx:
                    prompt_sql += f"HISTORIQUE RÉCENT :\n{historique_ctx}\n\n"
                prompt_sql += f"Question actuelle : {clean_question}"

                sql_raw   = llm_call_with_retry(llm, langfuse_handler, prompt_sql)
                match     = re.search(r"(SELECT|WITH).*?;", sql_raw, re.DOTALL | re.IGNORECASE)
                sql_clean = re.sub(r"```sql|```", "",
                                   match.group(0) if match else sql_raw).strip()

                with st.expander("🔍 Voir le SQL généré", expanded=False):
                    st.code(sql_clean, language="sql")

                if validate_sql(sql_clean):
                    sql_result  = router.executer_sql(sql_clean)
                    sql_latency = int((time.time() - t_sql_start) * 1000)

                    router.log_sql_result(
                        trace_id=trace_id, sql=sql_clean,
                        success=sql_result.success,
                        rows=len(sql_result.data) if sql_result.success and sql_result.data is not None else 0,
                        error=sql_result.error if not sql_result.success else "",
                        latency_ms=sql_latency,
                    )

                    if sql_result.success and not sql_result.data.empty:
                        st.dataframe(sql_result.data, use_container_width=True)
                        df_save = sql_result.data

                        analyse = (f"{FINAL_ANSWER_PROMPT}\n"
                                   f"Question : {clean_question}\n"
                                   f"Données :\n{sql_result.data.to_string(index=False)}")
                        try:
                            response = llm_call_with_retry(llm, langfuse_handler, analyse)
                        except Exception:
                            cols     = sql_result.data.columns.tolist()
                            nb       = len(sql_result.data)
                            response = (f"📊 {nb} résultat(s) trouvé(s). "
                                        f"Colonnes : {', '.join(cols)}. "
                                        f"Voir le tableau ci-dessus.")
                        st.markdown(response)

                        if veut_graphique and len(sql_result.data) >= 2:
                            fig = generer_graphique(sql_result.data, clean_question)
                            if fig:
                                st.plotly_chart(fig, use_container_width=True)
                                chart_save = fig
                            else:
                                st.info("💡 Graphique non disponible pour ces données.")
                        elif veut_graphique and len(sql_result.data) < 2:
                            st.info("ℹ️ Graphique non pertinent pour un résultat unique.")

                    else:
                        suggestion = suggerer_avec_rapidfuzz(current_query, router=router)
                        if suggestion:
                            st.session_state.suggestion_db    = suggestion
                            st.session_state.suggestion_query = current_query
                            response = f"Je cherche une alternative pour **\"{current_query}\"**…"
                        else:
                            response = "Aucun résultat trouvé pour cette recherche."
                            st.info(response)

                else:
                    response = "⚠️ Requête SQL interdite."
                    st.error(response)

            except Exception as e:
                response = str(e)
                st.error(f"❌ {response}")

            finally:
                router.finalize_trace(
                    trace_id=trace_id, response=response, intent="SQL",
                    total_latency_ms=int((time.time() - t_global_start) * 1000),
                )

    if response:
        st.session_state.messages.append({
            "role":    "assistant",
            "content": response,
            "data":    df_save,
            "chart":   chart_save,
        })

# fin app.py