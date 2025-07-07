# app.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from trueskill import Rating, rate, setup
from streamlit_gsheets import GSheetsConnection


st.set_page_config(page_title="Riichi League", page_icon="🀄")


def plus_minus(pts, place, oka, uma, target=30000):
    # place: 0-based rank after sorting descending points
    base = (pts - target) / 1000
    # zero-sum by design  [oai_citation:8‡riichi.wiki](https://riichi.wiki/Oka_and_uma?utm_source=chatgpt.com)
    return base + uma[place] + (oka / 1000 if place == 0 else 0)


# ---------------- Sidebar config ----------------
with st.sidebar:
    st.header("Scoring ↔ Rating Config")
    oka = st.number_input("Oka (winner bonus)", 0, 40000, 20000, step=1000)
    uma15 = st.number_input("Uma 1st", 0, 30, 15)
    uma5 = st.number_input("Uma 2nd", -30, 30, 5)
    uma_5 = st.number_input("Uma 3rd", -30, 30, -5)
    uma15m = st.number_input("Uma 4th", -30, 30, -15)
    target = st.number_input("Target score", 25000, 35000, 30000, step=1000)
    init_mu = st.number_input("Initial μ", 10.0, 35.0, 25.0, step=0.5)
    init_sig = st.number_input("Initial σ", 3.0, 10.0, 25 / 3, step=0.1)

uma = [uma15, uma5, uma_5, uma15m]

# ---------------- Load sheet ----------------
conn = st.connection("gsheets", type=GSheetsConnection)
# keep URL in secrets
SHEET_URL = st.secrets["gsheets"]["spreadsheet"]


# five-minute cache  [oai_citation:9‡docs.streamlit.io](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data?utm_source=chatgpt.com)
@st.cache_data(ttl=300)
def load_games(url):
    raw = conn.read(spreadsheet=url)
    return pd.DataFrame(raw)


df = load_games(SHEET_URL)

if df.empty:
    st.stop()

# tidy -> one row per player per game


def melt_games(df):
    tidy = []
    for idx, row in df.iterrows():
        gid = idx + 1
        for seat, off in zip(["East", "South", "West", "North"], range(0, 8, 2)):
            tidy.append(
                {
                    "GameID": gid,
                    "date": row["date"],
                    "Player": row[f"{seat} player"],
                    "Points": int(row[f"{seat} points"]),
                    "Seat": seat,
                }
            )
    return pd.DataFrame(tidy)


tidy = melt_games(df)

# ---------------- TrueSkill replay ----------------
setup(draw_probability=0.0, mu=init_mu, sigma=init_sig)  # global config
players = {}  # name -> Rating()
history = []  # collect snapshots for chart

for gid, g in tidy.groupby("GameID", sort=False):
    table = g.sort_values("Points", ascending=False)
    ratings_before = [players.get(p, Rating(init_mu, init_sig)) for p in table.Player]
    rating_groups = [[r] for r in ratings_before]
    rated_groups = rate(rating_groups, ranks=list(range(4)))
    ranks = list(range(4))  # 0..3 by Points desc
    ratings_after = [g[0] for g in rated_groups]
    for (pl, pts, seat), r0, r1, rk in zip(
        # <-- include Seat+Points
        zip(table.Player, table.Points, table.Seat),
        ratings_before,
        ratings_after,
        range(4),
    ):  # rank 0-3
        pm = plus_minus(pts, rk, oka, uma, target)
        players[pl] = r1
        history.append(
            {
                "GameID": gid,
                "Player": pl,
                "Seat": seat,
                "Points": pts,
                "μ": r1.mu,
                "σ": r1.sigma,
                "R": r1.mu - 3 * r1.sigma,
                "date": table.iloc[0]["date"],
                "±": pm,
            }
        )

hist_df = pd.DataFrame(history)
st.write("hist_df cols ➜", list(hist_df.columns))

# ---------------- Leaderboard ----------------
lb = (
    hist_df.sort_values("GameID")
    .groupby("Player")
    .tail(1)  # latest rating
    .sort_values("R", ascending=False)
)
st.subheader("Leaderboard (R = μ − 3σ)")
st.dataframe(
    lb[["Player", "R", "μ", "σ"]].style.format(
        {"R": "{:.2f}", "μ": "{:.2f}", "σ": "{:.2f}"}
    ),
    use_container_width=True,
)

# ---------------- Player filter & chart ----------------
player = st.selectbox("Show rating history for…", lb.Player)
sub = hist_df[hist_df.Player == player]

line = (
    alt.Chart(sub)
    .mark_line(point=True)
    .encode(x="GameID:O", y="R:Q", tooltip=["date", "±"])
    .properties(height=300, title=f"{player} rating history")
)
# streamlit theme  [oai_citation:10‡docs.streamlit.io](https://docs.streamlit.io/develop/api-reference/charts/st.altair_chart?utm_source=chatgpt.com)
st.altair_chart(line, use_container_width=True)

st.subheader("Game log")
st.dataframe(sub[["GameID", "date", "Seat", "Points", "±"]], use_container_width=True)
