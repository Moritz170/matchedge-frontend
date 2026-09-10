"""Streamlit Frontend (Read-Only via Supabase anon key and RLS).

Connects using public SUPABASE_ANON_KEY from st.secrets or environment variables.
Provides multi-league coverage across European football leagues:
- UEFA Champions League
- Premier League
- La Liga
- Serie A
- Bundesliga
- Ligue 1
"""

import os
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client

# Attempt to load from local or parent directory .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    parent_env = Path(__file__).resolve().parent.parent / "ucl_dixon_coles" / ".env"
    if parent_env.exists():
        load_dotenv(parent_env)
except ImportError:
    pass

st.set_page_config(
    page_title="Match Edge | Sportmodell Predictions",
    page_icon="⚽",
    layout="wide",
)


# Initialize Supabase client via Streamlit secrets (or fallback to env vars)
@st.cache_resource
def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        try:
            url = url or st.secrets.get("SUPABASE_URL")
            key = key or st.secrets.get("SUPABASE_ANON_KEY")
        except Exception:
            pass

    if not url or not key:
        st.error(
            "Missing SUPABASE_URL or SUPABASE_ANON_KEY. "
            "Please configure them in `.streamlit/secrets.toml`, environment variables, or a `.env` file."
        )
        st.stop()
    return create_client(url, key)


@st.cache_data(ttl=60)
def load_predictions():
    supabase = get_supabase_client()
    res = (
        supabase.table("predictions")
        .select("*")
        .order("match_date")
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=60)
def load_model_meta():
    supabase = get_supabase_client()
    res = (
        supabase.table("model_meta")
        .select("*")
        .order("fitted_at", desc=True)
        .execute()
    )
    return res.data or []


st.title("⚽ Sportmodell Prediction Pipeline — Match Edge")
st.markdown("Real-time Dixon-Coles Poisson probabilities and fair odds from Supabase across European football leagues.")

# Load data
predictions_data = load_predictions()
meta_data = load_model_meta()

# Model metadata display
if meta_data:
    st.subheader("📊 Calibrated League Models")

    def get_league_info(version_str):
        v = (version_str or "").lower()
        if "premier" in v:
            return "premier_league", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", 1
        elif "laliga" in v:
            return "laliga", "🇪🇸 La Liga", 2
        elif "serie_a" in v:
            return "serie_a", "🇮🇹 Serie A", 3
        elif "bundesliga" in v:
            return "bundesliga", "🇩🇪 Bundesliga", 4
        elif "ligue1" in v:
            return "ligue1", "🇫🇷 Ligue 1", 5
        elif "ucl" in v:
            return "ucl", "🏆 Champions League", 0
        return v, "⚽ Model", 6

    # Keep latest model run per league (meta_data is ordered by fitted_at DESC)
    latest_by_competition = {}
    for m in meta_data:
        v = m.get("model_version", "Unknown")
        comp_key, badge, order_idx = get_league_info(v)
        if comp_key not in latest_by_competition:
            latest_by_competition[comp_key] = (m, badge, order_idx)

    sorted_models = sorted(latest_by_competition.values(), key=lambda x: x[2])
    num_cols = 3
    for row_start in range(0, len(sorted_models), num_cols):
        row_items = sorted_models[row_start:row_start + num_cols]
        cols = st.columns(len(row_items))
        for i, (meta, badge, _) in enumerate(row_items):
            with cols[i]:
                st.info(
                    f"**{badge}** (`{meta.get('model_version')}`)\n\n"
                    f"• **Home Advantage:** `{meta.get('home_advantage')}`\n\n"
                    f"• **Rho:** `{meta.get('rho')}`\n\n"
                    f"• **Fitted:** `{str(meta.get('fitted_at'))[:16]}`"
                )

if not predictions_data:
    st.warning("No predictions found in Supabase yet. Run the pipeline to populate predictions.")
else:
    df = pd.DataFrame(predictions_data)

    # Competition filter
    competitions = ["All Leagues"] + sorted(list(df["competition"].dropna().unique()))
    selected_comp = st.selectbox("Filter by Competition:", competitions, index=0)

    if selected_comp != "All Leagues":
        df = df[df["competition"] == selected_comp].copy()

    # Format display columns safely
    display_df = df.copy()
    for col, out_col in [("home_win_prob", "home_win"), ("draw_prob", "draw"), ("away_win_prob", "away_win")]:
        if col in display_df.columns:
            display_df[out_col] = display_df[col].apply(
                lambda x: f"{round(float(x) * 100, 1)}%" if pd.notnull(x) else "-"
            )

    # Format match dates cleanly
    if "match_date" in display_df.columns:
        display_df["match_date"] = display_df["match_date"].apply(
            lambda d: str(d).replace("T", " ")[:16] if pd.notnull(d) else "-"
        )

    cols_order = [
        "match_date", "competition", "home_team", "away_team",
        "home_win", "draw", "away_win",
        "expected_home_goals", "expected_away_goals", "model_version"
    ]
    existing_cols = [c for c in cols_order if c in display_df.columns]

    st.dataframe(
        display_df[existing_cols],
        width="stretch",
        hide_index=True,
    )
