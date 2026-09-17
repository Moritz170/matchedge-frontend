"""MatchEdge Multi-Sport Quantitative Valuation Web Application.

Provides automated, real-time sports valuation without any manual CLI execution:
- 🏈 NFL American Football: Always shows upcoming games with countdowns to place bets in time,
  auto-detects active matchdays, evaluates offensive/defensive simulations, and auto-reconciles finished results.
- ⚽ European Football: Live Dixon-Coles Poisson model probabilities and fair odds.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import streamlit as st
from supabase import create_client

# Ensure project root is in sys.path
CURRENT_FILE = Path(__file__).resolve()
WORKSPACE_ROOT = CURRENT_FILE.parent.parent
UCL_ROOT = WORKSPACE_ROOT / "ucl_dixon_coles"
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

# Attempt to load from local or parent directory .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    parent_env = UCL_ROOT / ".env"
    if parent_env.exists():
        load_dotenv(parent_env)
except ImportError:
    pass

st.set_page_config(
    page_title="MatchEdge | Multi-Sport Quantitative Valuation",
    page_icon="⚡",
    layout="wide",
)

# Custom CSS for rich aesthetics
st.markdown("""
<style>
    .metric-card {
        background-color: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        padding: 14px;
        text-align: center;
    }
    .badge-countdown {
        background-color: #00e5ff;
        color: #000;
        padding: 3px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.85rem;
    }
    .badge-live {
        background-color: #ff1744;
        color: #fff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .badge-final {
        background-color: #78909c;
        color: #fff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# SUPABASE CLIENT
# =============================================================================

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
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# =============================================================================
# AUTOMATED NFL DATA ENGINE (ALWAYS PULLS UPCOMING SLATE ON LOAD)
# =============================================================================

@st.cache_data(ttl=900)  # Automatically re-evaluates every 15 minutes
def load_automated_nfl_matchday(target_week: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any], int, int]:
    """Loads NFL matchday data.
    
    Always guarantees that upcoming games are available so bettors can place bets in time:
    - Auto-advances if all games in a week are completed.
    - If target_week has few/zero upcoming games left, stitches upcoming games from next week.
    """
    try:
        from ucl_dixon_coles.nfl.pipeline import NFLPipeline
        pipeline = NFLPipeline(week=target_week)
        pipeline.ingest_inputs()
        val_df = pipeline.run_valuation()
        pipeline.save_outputs()

        # Auto-reconcile completed games
        recon_summary = pipeline.reconcile_completed_games()

        # Silently attempt Supabase sync in background
        try:
            pipeline.sync_to_supabase()
        except Exception:
            pass

        records = val_df.to_dict(orient="records")
        return records, recon_summary, pipeline.season, pipeline.week

    except Exception as e:
        # Fallback to local cached JSON if offline or error
        fallback_file = UCL_ROOT / "outputs" / "nfl" / f"nfl_season2026_week{target_week or 2}_valuation.json"
        if not fallback_file.exists():
            fallback_file = UCL_ROOT / "outputs" / "nfl" / "nfl_season2026_week2_valuation.json"
        if fallback_file.exists():
            try:
                with open(fallback_file, "r") as f:
                    return json.load(f), {"reconciled_count": 0}, 2026, target_week or 2
            except Exception:
                pass
        return [], {"error": str(e)}, 2026, target_week or 2


# =============================================================================
# FOOTBALL (SOCCER) DATA LOADERS
# =============================================================================

@st.cache_data(ttl=60)
def load_soccer_predictions():
    supabase = get_supabase_client()
    if not supabase:
        return []
    try:
        res = supabase.table("predictions").select("*").order("match_date").execute()
        return res.data or []
    except Exception:
        return []


@st.cache_data(ttl=60)
def load_soccer_meta():
    supabase = get_supabase_client()
    if not supabase:
        return []
    try:
        res = supabase.table("model_meta").select("*").order("fitted_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================

st.sidebar.title("⚡ MATCHEDGE")
st.sidebar.markdown("**Live Quantitative Betting Engine**")

sport_choice = st.sidebar.radio(
    "Choose Sport Pipeline:",
    ["🏈 NFL American Football", "⚽ European Football"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Automation Status**:\n\n"
    "• 🟢 **Upcoming Games Feed**: Active\n\n"
    "• ⏱️ **Auto-Refresh Interval**: 15 Minutes\n\n"
    "• 🛡️ **Risk Sizing**: Quarter-Kelly ($f^* / 4$)"
)

# Manual Force Refresh Button
if st.sidebar.button("🔄 Force Live Refresh Now"):
    st.cache_data.clear()
    st.rerun()


# =============================================================================
# VIEW 1: NFL AMERICAN FOOTBALL (UPCOMING-FIRST BETTING VIEW)
# =============================================================================

if "NFL" in sport_choice:
    # Matchday Selector in sidebar or top
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Matchday Controls")
    week_option = st.sidebar.selectbox(
        "Select Matchday Slate:",
        [
            "⚡ Auto (Next Upcoming Slate)",
            "Week 2 (Active Matchday)",
            "Week 3 (Next Matchday)",
            "Week 4 (Future)",
            "Week 1 (Final Archive)",
        ],
        index=0,
    )

    selected_week = None
    if "Week 1" in week_option:
        selected_week = 1
    elif "Week 2" in week_option:
        selected_week = 2
    elif "Week 3" in week_option:
        selected_week = 3
    elif "Week 4" in week_option:
        selected_week = 4

    # Load current matchday automatically on page load
    with st.spinner("🤖 Auto-loading upcoming NFL games, live odds, and injury reports..."):
        nfl_records, recon_info, cur_season, cur_week = load_automated_nfl_matchday(target_week=selected_week)

    st.title(f"🏈 MatchEdge NFL — Season {cur_season} Week {cur_week}")
    st.markdown(
        f"**Live Upcoming Betting Feed** • Evaluated **{len(nfl_records)} matchups** with model valuations. "
        "Upcoming games are prioritized with time countdowns so you can place your bets in time before kickoff."
    )

    if not nfl_records:
        st.warning("Loading live schedule from ESPN... Please refresh in a moment.")
    else:
        df_nfl = pd.DataFrame(nfl_records)

        # Split into upcoming and finished games
        now_utc = datetime.now(timezone.utc)
        upcoming_rows = [r for r in nfl_records if r.get("status") != "STATUS_FINAL"]
        # Sort upcoming games chronologically so the soonest kickoff is at the very top!
        upcoming_rows.sort(key=lambda x: (x.get("starts_in_hours") is None, x.get("starts_in_hours") or 9999))

        finished_rows = [r for r in nfl_records if r.get("status") == "STATUS_FINAL"]

        # Overview Metrics Row
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Upcoming Games to Bet", len(upcoming_rows), delta=f"{len(upcoming_rows)} unplayed")
        with col2:
            spread_edges = len([r for r in upcoming_rows if r.get("spread_pick") in ["HOME", "AWAY"]])
            st.metric("Actionable Spread Bets", spread_edges)
        with col3:
            total_edges = len([r for r in upcoming_rows if r.get("total_pick") in ["OVER", "UNDER"]])
            st.metric("Actionable Total Bets", total_edges)
        with col4:
            avg_score = round(float(df_nfl["matchedge_score"].mean()), 1) if "matchedge_score" in df_nfl.columns else 0.0
            st.metric("Avg MatchEdge Score", f"{avg_score} / 10")

        st.markdown("---")

        tabs = st.tabs([
            "⚡ Next Upcoming Games to Bet On",
            "📋 Full Matchday Slate & Table",
            "🏆 Completed Results & Graded ROI",
        ])

        # TAB 1: NEXT UPCOMING GAMES TO BET ON
        with tabs[0]:
            if not upcoming_rows:
                st.info(
                    f"All games for Week {cur_week} are already completed! "
                    "Select **Week 3** from the sidebar to view the next upcoming matchday."
                )
            else:
                f_col1, f_col2 = st.columns([1, 2])
                with f_col1:
                    filter_choice = st.selectbox(
                        "Filter Upcoming Games:",
                        ["All Upcoming Games", "Top Value Picks (Score >= 8.5)", "Point Spread Only", "Game Total Only"],
                    )

                display_upcoming = upcoming_rows
                if filter_choice == "Top Value Picks (Score >= 8.5)":
                    display_upcoming = [r for r in upcoming_rows if r.get("matchedge_score", 0) >= 8.5]
                elif filter_choice == "Point Spread Only":
                    display_upcoming = [r for r in upcoming_rows if r.get("spread_pick") in ["HOME", "AWAY"]]
                elif filter_choice == "Game Total Only":
                    display_upcoming = [r for r in upcoming_rows if r.get("total_pick") in ["OVER", "UNDER"]]

                st.caption(f"Showing **{len(display_upcoming)} upcoming games** sorted by earliest kickoff:")

                for row in display_upcoming:
                    h_team = row.get("home_team", "Home")
                    a_team = row.get("away_team", "Away")
                    h_abbr = row.get("home_team_abbr", "HOM")
                    a_abbr = row.get("away_team_abbr", "AWY")
                    g_date = str(row.get("kickoff_formatted") or row.get("game_date", ""))[:16]
                    score = row.get("matchedge_score", 5.0)
                    verdict = row.get("verdict", "")
                    starts_h = row.get("starts_in_hours")

                    # Friendly countdown badge
                    if starts_h is not None:
                        if starts_h > 24:
                            days = round(starts_h / 24.0, 1)
                            time_badge = f"⏳ Kickoff in {days} days"
                        elif starts_h > 0:
                            time_badge = f"⏳ Kickoff in {starts_h:.1f} hours"
                        else:
                            time_badge = "🔴 Live / Kickoff imminent"
                    else:
                        time_badge = "⏱️ Scheduled"

                    with st.expander(
                        f"**{a_team} ({a_abbr}) @ {h_team} ({h_abbr})** — `{time_badge}` — MatchEdge Score: **{score}/10**",
                        expanded=True,
                    ):
                        c1, c2, c3 = st.columns([1.2, 1.2, 1.6])

                        with c1:
                            st.markdown("#### 🎯 Point Spread Market")
                            m_spread = row.get("market_spread")
                            p_spread = row.get("projected_spread")
                            sp_pick = row.get("spread_pick", "PASS")
                            sp_edge = row.get("spread_edge", 0.0)
                            sp_kelly = row.get("spread_kelly", 0.0)

                            st.write(f"• **Market Line:** `{m_spread:+.1f}`" if m_spread is not None else "• **Market Line:** N/A")
                            st.write(f"• **Model Fair Spread:** `{p_spread:+.1f}`" if p_spread is not None else "• **Model Fair Spread:** N/A")
                            if sp_pick != "PASS":
                                pick_team = h_abbr if sp_pick == "HOME" else a_abbr
                                st.success(f"**TARGET: {pick_team}** (+{sp_edge * 100:.1f}% EV)")
                                st.caption(f"Quarter-Kelly Stake: **{sp_kelly * 100:.1f}% of bankroll**")
                            else:
                                st.info("Pick: PASS (Line is fair)")

                        with c2:
                            st.markdown("#### ⚖️ Over / Under Total")
                            m_tot = row.get("market_total")
                            p_tot = row.get("projected_total")
                            t_pick = row.get("total_pick", "PASS")
                            t_edge = row.get("total_edge", 0.0)
                            t_kelly = row.get("total_kelly", 0.0)

                            st.write(f"• **Market Total:** `{m_tot:.1f}`" if m_tot is not None else "• **Market Total:** N/A")
                            st.write(f"• **Model Projected Total:** `{p_tot:.1f}`" if p_tot is not None else "• **Model Projected Total:** N/A")
                            if t_pick != "PASS":
                                st.success(f"**TARGET: {t_pick} {m_tot}** (+{t_edge * 100:.1f}% EV)")
                                st.caption(f"Quarter-Kelly Stake: **{t_kelly * 100:.1f}% of bankroll**")
                            else:
                                st.info("Pick: PASS (Total is fair)")

                        with c3:
                            st.markdown("#### 🧠 Quarterbacks & Best Verdict")
                            h_qb = row.get("home_qb_name", "Starter")
                            a_qb = row.get("away_qb_name", "Starter")
                            net_qb = row.get("net_qb_impact", 0.0)
                            st.write(f"• **Starting QBs:** `{h_abbr}: {h_qb}` vs `{a_abbr}: {a_qb}`")
                            if abs(net_qb) >= 1.0:
                                fav_qb = h_qb if net_qb > 0 else a_qb
                                st.caption(f"QB Advantage: {fav_qb} ({net_qb:+.1f} pts)")
                            st.write(f"• **Verdict:** *{verdict}*")
                            st.caption(f"Kickoff: `{g_date} UTC`")

                        # Why points breakdown
                        why_pts = row.get("why_points", [])
                        if isinstance(why_pts, str):
                            try:
                                why_pts = json.loads(why_pts)
                            except Exception:
                                why_pts = [why_pts]
                        if why_pts:
                            st.markdown("**Tactical Advantage Breakdown:**")
                            for pt in why_pts:
                                st.markdown(f"- {pt}")

        # TAB 2: FULL MATCHDAY SLATE & MODEL TABLE
        with tabs[1]:
            st.subheader(f"Complete Evaluated Slate — Week {cur_week}")
            cols_show = [
                "game_date", "home_team_abbr", "away_team_abbr", "status",
                "market_spread", "projected_spread", "spread_pick", "spread_edge",
                "market_total", "projected_total", "total_pick", "total_edge",
                "matchedge_score", "verdict"
            ]
            exist = [c for c in cols_show if c in df_nfl.columns]
            st.dataframe(df_nfl[exist], hide_index=True, width="stretch")

        # TAB 3: COMPLETED RESULTS & GRADED ROI
        with tabs[2]:
            st.subheader("📊 Automated Results Reconciliation & Profit Tracking")
            st.markdown(
                "When games conclude, official scores are automatically ingested and every bet is graded "
                "Against the Spread (ATS) and Over/Under."
            )
            r_col1, r_col2, r_col3 = st.columns(3)
            with r_col1:
                st.metric("Games Graded This Week", recon_info.get("reconciled_count", 0))
            with r_col2:
                st.metric("Spread Record", recon_info.get("spread_record", "0-0"))
            with r_col3:
                pnl = recon_info.get("net_pnl_units", 0.0)
                st.metric("Net Profit / Loss", f"{pnl:+.2f} Units", delta=f"{pnl:+.2f}")

            # Completed games from active week
            if finished_rows:
                st.markdown(f"#### Finished Games in Week {cur_week}")
                df_fin = pd.DataFrame(finished_rows)
                fin_cols = ["home_team", "away_team", "home_score", "away_score", "market_spread", "spread_pick", "market_total", "total_pick", "verdict"]
                exist_fin = [c for c in fin_cols if c in df_fin.columns]
                st.dataframe(df_fin[exist_fin], hide_index=True, width="stretch")

            # Check if Week 1 archive exists
            w1_archive = UCL_ROOT / "outputs" / "nfl" / "nfl_season2026_week1_reconciliation.json"
            if w1_archive.exists():
                try:
                    with open(w1_archive, "r") as f:
                        w1_data = json.load(f)
                    st.markdown("#### Completed Results Archive (Week 1)")
                    df_w1 = pd.DataFrame(w1_data)
                    w1_cols = ["home_team", "away_team", "actual_home_score", "actual_away_score", "market_spread", "spread_result", "market_total", "total_result", "total_pnl_units"]
                    exist_w1 = [c for c in w1_cols if c in df_w1.columns]
                    st.dataframe(df_w1[exist_w1], hide_index=True, width="stretch")
                except Exception:
                    pass


# =============================================================================
# VIEW 2: EUROPEAN FOOTBALL (SOCCER)
# =============================================================================

else:
    st.title("⚽ Sportmodell Prediction Pipeline — Match Edge")
    st.markdown("Real-time Dixon-Coles Poisson probabilities and fair odds across European football leagues.")

    predictions_data = load_soccer_predictions()
    meta_data = load_soccer_meta()

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

        competitions = ["All Leagues"] + sorted(list(df["competition"].dropna().unique()))
        selected_comp = st.selectbox("Filter by Competition:", competitions, index=0)

        if selected_comp != "All Leagues":
            df = df[df["competition"] == selected_comp].copy()

        display_df = df.copy()
        for col, out_col in [("home_win_prob", "home_win"), ("draw_prob", "draw"), ("away_win_prob", "away_win")]:
            if col in display_df.columns:
                display_df[out_col] = display_df[col].apply(
                    lambda x: f"{round(float(x) * 100, 1)}%" if pd.notnull(x) else "-"
                )

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
