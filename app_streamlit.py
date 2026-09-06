"""Streamlit Frontend (Read-Only via Supabase anon key and RLS).

As specified in the Database Setup & Connection Guide:
- Connects using public SUPABASE_ANON_KEY from st.secrets
- Read-only access enforced by Postgres Row Level Security (RLS)
- Completely decoupled from the pipeline
"""

import os
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Match Edge | Sportmodell Predictions",
    page_icon="⚽",
    layout="wide",
)

# Initialize Supabase client via Streamlit secrets (or fallback to env vars)
@st.cache_resource
def get_supabase_client():
    url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL"))
    key = st.secrets.get("SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY"))
    if not url or not key:
        st.error("Missing SUPABASE_URL or SUPABASE_ANON_KEY in secrets.toml or environment variables.")
        st.stop()
    return create_client(url, key)


def load_predictions():
    supabase = get_supabase_client()
    res = (
        supabase.table("predictions")
        .select("*")
        .order("match_date")
        .execute()
    )
    return res.data or []


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
st.markdown("Real-time Dixon-Coles Poisson probabilities and fair odds from Supabase.")

# Load data
predictions_data = load_predictions()
meta_data = load_model_meta()

if meta_data:
    latest_meta = meta_data[0]
    st.info(
        f"**Active Model Run:** `{latest_meta.get('model_version')}` | "
        f"**Home Advantage:** `{latest_meta.get('home_advantage')}` | "
        f"**Rho:** `{latest_meta.get('rho')}` | "
        f"**Fitted At:** `{latest_meta.get('fitted_at')}`"
    )

if not predictions_data:
    st.warning("No predictions found in Supabase yet. Run the pipeline to populate predictions.")
else:
    df = pd.DataFrame(predictions_data)
    
    # Format display columns
    cols_order = [
        "match_date", "competition", "home_team", "away_team",
        "home_win_prob", "draw_prob", "away_win_prob",
        "expected_home_goals", "expected_away_goals", "model_version"
    ]
    existing_cols = [c for c in cols_order if c in df.columns]
    
    st.dataframe(
        df[existing_cols],
        use_container_width=True,
        hide_index=True,
    )
