import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, date
import statsapi
from pybaseball import playerid_reverse_lookup, statcast_pitcher, statcast_batter
import feedparser
import pytz

# MLB Season Settings
TOKYO_START   = datetime(2025, 3, 18)
TOKYO_2       = datetime(2025, 3, 19)
REGULAR_START = datetime(2025, 3, 27)
ROYAL_BLUE = "#1E90FF"
ORANGE     = "#FF8000"

st.set_page_config(layout="wide", page_title="MLB 2025 Tracker")

# --- NEWS (RSS-based) ---
def fetch_mlb_news_rss():
    url = "https://www.mlb.com/feeds/news/rss.xml"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "summary": entry.summary if 'summary' in entry else '',
            "published": entry.published if 'published' in entry else ''
        })
    return articles

def is_valid_news(article):
    teaser_keywords = ["vote", "voting", "check back", "countdown", "announcement"]
    content = (article["title"] + " " + article["summary"]).lower()
    if any(kw in content for kw in teaser_keywords):
        return False
    if len(article["summary"].strip()) == 0 and len(article["title"].strip()) == 0:
        return False
    return True

# --- TEAM INFO ---
@st.cache_data(ttl=12 * 60 * 60)
def get_team_info():
    teams_raw = statsapi.get('teams', {'sportIds': 1})['teams']
    team_info = {}
    for t in teams_raw:
        if t['active']:
            abbr = t['abbreviation']
            team_info[abbr] = {
                'id': t['id'],
                'name': t['name'],
                'logo': f"https://www.mlbstatic.com/team-logos/{t['id']}.svg",
                'slug': t.get('teamName', '').lower().replace(' ', '-'),
                'division': t['division']['name']
            }
    return team_info

team_info = get_team_info()
team_abbrs = sorted(team_info.keys())
team_names = [team_info[a]['name'] for a in team_abbrs]
abbr_by_name = {team_info[a]['name']: a for a in team_abbrs}

# --- PLAYERS ---
@st.cache_data(ttl=12 * 60 * 60)
def build_rosters():
    teams_raw = statsapi.get('teams', {'sportIds': 1})['teams']
    active_teams = [t for t in teams_raw if t['active']]
    batters = []
    pitchers = []
    for team in active_teams:
        data = statsapi.get('team_roster', {
            'teamId': team['id'],
            'rosterType': 'active'
        })
        for player in data.get('roster', []):
            person = player.get('person', {})
            name   = person.get('fullName')
            pid    = person.get('id')
            pos    = player.get('position', {}).get('abbreviation', "")
            if name and pid:
                if pos == "P":
                    pitchers.append((name, pid, team['abbreviation']))
                else:
                    batters.append((name, pid, team['abbreviation']))
    return batters, pitchers

batters, pitchers = build_rosters()
batter_map  = {name: (pid, team) for name, pid, team in batters}
pitcher_map = {name: (pid, team) for name, pid, team in pitchers}

# --- ALWAYS add Shohei Ohtani as a pitcher for selection ---
OTANI_NAME = "Shohei Ohtani"
OTANI_ID = 660271
OTANI_TEAM = "LAD"
if OTANI_NAME not in pitcher_map:
    pitchers.insert(0, (OTANI_NAME, OTANI_ID, OTANI_TEAM))
    pitcher_map[OTANI_NAME] = (OTANI_ID, OTANI_TEAM)

# --- PLAYER IMAGE ---
def get_player_image(pid: int) -> str:
    return (f"https://img.mlbstatic.com/mlb-photos/image/upload/"
            f"w_180,q_100/v1/people/{pid}/headshot/67/current.png")

# --- DATA FETCH ---
def fetch_hr_log(pid: int, start: datetime, end: datetime, team_abbr: str) -> pd.DataFrame:
    df = statcast_batter(
        start_dt=start.strftime('%Y-%m-%d'),
        end_dt=end.strftime('%Y-%m-%d'),
        player_id=str(pid)
    )
    if df.empty:
        return df
    df['Date'] = pd.to_datetime(df['game_date'])
    tokyo_days = [TOKYO_START, TOKYO_2]
    if team_abbr in {'LAD', 'CHC'}:
        mask = df['Date'].isin(tokyo_days) | (df['Date'] >= REGULAR_START)
    else:
        mask = df['Date'] >= REGULAR_START
    df = df.loc[mask]
    df_hr = (df[df['events'] == 'home_run']
             .copy()
             .sort_values('Date')
             .reset_index(drop=True))
    if df_hr.empty:
        return df_hr
    df_hr['HR No'] = df_hr.index + 1
    df_hr['MM-DD'] = df_hr['Date'].dt.strftime('%m-%d')
    def pid2name(p):
        try:
            t = playerid_reverse_lookup([p], key_type='mlbam')
            return t['name_first'][0] + ' ' + t['name_last'][0]
        except Exception:
            return str(p)
    df_hr['Pitcher'] = df_hr['pitcher'].apply(
        lambda x: pid2name(x) if pd.notna(x) else '')
    return df_hr

def fetch_k_log(pid: int, start: datetime, end: datetime, team_abbr: str) -> pd.DataFrame:
    df = statcast_pitcher(
        start_dt=start.strftime('%Y-%m-%d'),
        end_dt=end.strftime('%Y-%m-%d'),
        player_id=str(pid)
    )
    if df.empty:
        return df
    df['Date'] = pd.to_datetime(df['game_date'])
    tokyo_days = [TOKYO_START, TOKYO_2]
    if team_abbr in {'LAD', 'CHC'}:
        mask = df['Date'].isin(tokyo_days) | (df['Date'] >= REGULAR_START)
    else:
        mask = df['Date'] >= REGULAR_START
    df = df.loc[mask]
    df_k = (df[df['events'] == 'strikeout']
             .copy()
             .sort_values('Date')
             .reset_index(drop=True))
    if df_k.empty:
        return df_k
    df_k['K No'] = df_k.index + 1
    df_k['MM-DD'] = df_k['Date'].dt.strftime('%m-%d')
    def pid2name(p):
        try:
            t = playerid_reverse_lookup([p], key_type='mlbam')
            return t['name_first'][0] + ' ' + t['name_last'][0]
        except Exception:
            return str(p)
    df_k['Batter'] = df_k['batter'].apply(
        lambda x: pid2name(x) if pd.notna(x) else '')
    return df_k

# --- SIDEBAR ---
tracker = st.sidebar.radio(
    "Select Tracker", 
    ["Home Run Tracker", "Strikeout Tracker"], 
    key="tracker_tab"
)

# --- MAIN ---
if tracker == "Home Run Tracker":
    st.sidebar.header("Select Batters and Date Range")
    st.sidebar.info(
        "Note: Only players currently on the official MLB active roster are shown. "
        "Players not on an active roster will not appear."
    )

    default_team1 = "Los Angeles Dodgers"
    team1_name = st.sidebar.selectbox(
        "First Player's Team", team_names,
        index=team_names.index(default_team1) if default_team1 in team_names else 0,
        key="hr_team1")
    team1_abbr = abbr_by_name[team1_name]
    team1_batters = [n for n, _, t in batters if t == team1_abbr]
    default_player1 = "Shohei Ohtani"
    player1_name = st.sidebar.selectbox(
        "First Player", team1_batters,
        index=team1_batters.index(default_player1) if default_player1 in team1_batters else 0,
        key="hr_player1")

    default_team2 = "New York Yankees"
    team2_name = st.sidebar.selectbox(
        "Second Player's Team", team_names,
        index=team_names.index(default_team2) if default_team2 in team_names else 0,
        key="hr_team2")
    team2_abbr = abbr_by_name[team2_name]
    team2_batters = [n for n, _, t in batters if t == team2_abbr]
    default_player2 = "Aaron Judge"
    player2_name = st.sidebar.selectbox(
        "Second Player", team2_batters,
        index=team2_batters.index(default_player2) if default_player2 in team2_batters else 0,
        key="hr_player2")

    start_date = st.sidebar.date_input("Start date", TOKYO_START, key="hr_start")
    end_date   = st.sidebar.date_input("End date", date.today(), key="hr_end")

    # MLB Teams Official Links
    st.sidebar.markdown("#### MLB Teams (official site links)")
    division_map = {
        'American League': {'East': [], 'Central': [], 'West': []},
        'National League': {'East': [], 'Central': [], 'West': []}
    }
    division_name_map = {
        'American League East': ('American League', 'East'),
        'American League Central': ('American League', 'Central'),
        'American League West': ('American League', 'West'),
        'National League East': ('National League', 'East'),
        'National League Central': ('National League', 'Central'),
        'National League West': ('National League', 'West')
    }
    for abbr in team_abbrs:
        info = team_info[abbr]
        div_full = info['division']
        league, division = division_name_map[div_full]
        url = f"https://www.mlb.com/{info['slug']}"
        entry = (
            f'<a href="{url}" target="_blank">'
            f'<img src="{info["logo"]}" width="22" style="vertical-align:middle;margin-right:4px;">'
            f'{abbr}</a>'
        )
        division_map[league][division].append(entry)
    def render_division_block_sidebar(division, entries):
        st.sidebar.markdown(f"**{division}**")
        col_count = 6
        rows = [entries[i:i+col_count] for i in range(0, len(entries), col_count)]
        table_html = '<table style="border-collapse:collapse;border:none;">'
        for row in rows:
            table_html += '<tr style="border:none;">' + ''.join(
                f'<td style="padding:2px 8px;border:none;background:transparent;">{cell}</td>' for cell in row
            ) + '</tr>'
        table_html += '</table>'
        st.sidebar.markdown(table_html, unsafe_allow_html=True)
    for league in ['American League', 'National League']:
        st.sidebar.markdown(f"### {league}")
        for division in ['East', 'Central', 'West']:
            entries = division_map[league][division]
            if entries:
                render_division_block_sidebar(division, entries)

    # Main content for Home Run Tracker
    st.title("MLB Home Run Pace Comparison — 2025 Season")

    no_game_msgs = []
    if team1_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
        no_game_msgs.append(f"No official MLB games for {player1_name} ({team1_abbr}) before 2025-03-27.")
    if team2_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
        no_game_msgs.append(f"No official MLB games for {player2_name} ({team2_abbr}) before 2025-03-27.")
    if no_game_msgs:
        for msg in no_game_msgs:
            st.warning(msg)

    p1_id, team1_code = batter_map[player1_name]
    p2_id, team2_code = batter_map[player2_name]
    col1, col2 = st.columns(2)
    logs = {}
    color_map = {player1_name: ROYAL_BLUE, player2_name: ORANGE}
    for col, pid, name, code in [
        (col1, p1_id, player1_name, team1_code),
        (col2, p2_id, player2_name, team2_code)
    ]:
        with col:
            st.subheader(f"{name} ({team_info[code]['name']})")
            st.image(get_player_image(pid), width=100)
            df_hr = fetch_hr_log(
                pid,
                datetime.combine(start_date, datetime.min.time()),
                end_date,
                code
            )
            logs[name] = df_hr
            if df_hr.empty:
                st.info("No HR data in selected period.")
                continue
            st.dataframe(
                df_hr[['HR No', 'MM-DD', 'home_team', 'away_team', 'Pitcher']],
                use_container_width=True)
            chart = (alt.Chart(df_hr)
                    .mark_line(point=False, color=color_map[name])
                    .encode(
                        x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
                        y=alt.Y('HR No:Q', title='Cumulative HRs', axis=alt.Axis(format='d'))
                    ) +
                    alt.Chart(df_hr)
                    .mark_point(size=60, filled=True, color=color_map[name])
                    .encode(x='Date:T', y='HR No:Q'))
            st.altair_chart(chart.properties(title=f"{name} HR Pace"), use_container_width=True)

    if all(not logs[n].empty for n in [player1_name, player2_name]):
        st.subheader("Head-to-Head Comparison")
        merged = pd.concat([
            logs[player1_name].assign(Player=player1_name),
            logs[player2_name].assign(Player=player2_name)
        ])
        comparison = (
            alt.Chart(merged)
            .mark_line(point=False)
            .encode(
                x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
                y=alt.Y('HR No:Q', title='Cumulative HRs', axis=alt.Axis(format='d')),
                color=alt.Color('Player:N', scale=alt.Scale(
                    domain=[player1_name, player2_name],
                    range=[ROYAL_BLUE, ORANGE])),
                tooltip=['Player', 'Date', 'HR No', 'Pitcher']
            )
            + alt.Chart(merged)
            .mark_point(size=60, filled=True)
            .encode(x='Date:T', y='HR No:Q', color='Player:N')
        )
        st.altair_chart(comparison, use_container_width=True)

    st.caption("Game data: Statcast (pybaseball), Rosters: MLB-StatsAPI | News: MLB.com RSS feed")

elif tracker == "Strikeout Tracker":
    st.sidebar.header("Select Pitchers and Date Range")
    st.sidebar.info(
        "Note: Only pitchers currently on the official MLB active roster are shown. "
        "Pitchers not on an active roster will not appear."
    )

    default_team1 = "Los Angeles Dodgers"
    team1_name = st.sidebar.selectbox(
        "First Pitcher's Team", team_names,
        index=team_names.index(default_team1) if default_team1 in team_names else 0,
        key="k_team1")
    team1_abbr = abbr_by_name[team1_name]
    team1_pitchers = [n for n, _, t in pitchers if t == team1_abbr]
    if OTANI_NAME not in team1_pitchers and team1_abbr == OTANI_TEAM:
        team1_pitchers.insert(0, OTANI_NAME)
    default_pitcher1 = "Yoshinobu Yamamoto"
    pitcher1_name = st.sidebar.selectbox(
        "First Pitcher", team1_pitchers,
        index=team1_pitchers.index(default_pitcher1) if default_pitcher1 in team1_pitchers else 0,
        key="k_pitcher1")

    default_team2 = "Chicago Cubs"
    team2_name = st.sidebar.selectbox(
        "Second Pitcher's Team", team_names,
        index=team_names.index(default_team2) if default_team2 in team_names else 0,
        key="k_team2")
    team2_abbr = abbr_by_name[team2_name]
    team2_pitchers = [n for n, _, t in pitchers if t == team2_abbr]
    default_pitcher2 = "Shota Imanaga"
    pitcher2_name = st.sidebar.selectbox(
        "Second Pitcher", team2_pitchers,
        index=team2_pitchers.index(default_pitcher2) if default_pitcher2 in team2_pitchers else 0,
        key="k_pitcher2")

    start_date = st.sidebar.date_input("Start date", TOKYO_START, key="k_start")
    end_date   = st.sidebar.date_input("End date", date.today(), key="k_end")

    # MLB Teams Official Links
    st.sidebar.markdown("#### MLB Teams (official site links)")
    division_map = {
        'American League': {'East': [], 'Central': [], 'West': []},
        'National League': {'East': [], 'Central': [], 'West': []}
    }
    division_name_map = {
        'American League East': ('American League', 'East'),
        'American League Central': ('American League', 'Central'),
        'American League West': ('American League', 'West'),
        'National League East': ('National League', 'East'),
        'National League Central': ('National League', 'Central'),
        'National League West': ('National League', 'West')
    }
    for abbr in team_abbrs:
        info = team_info[abbr]
        div_full = info['division']
        league, division = division_name_map[div_full]
        url = f"https://www.mlb.com/{info['slug']}"
        entry = (
            f'<a href="{url}" target="_blank">'
            f'<img src="{info["logo"]}" width="22" style="vertical-align:middle;margin-right:4px;">'
            f'{abbr}</a>'
        )
        division_map[league][division].append(entry)
    def render_division_block_sidebar(division, entries):
        st.sidebar.markdown(f"**{division}**")
        col_count = 6
        rows = [entries[i:i+col_count] for i in range(0, len(entries), col_count)]
        table_html = '<table style="border-collapse:collapse;border:none;">'
        for row in rows:
            table_html += '<tr style="border:none;">' + ''.join(
                f'<td style="padding:2px 8px;border:none;background:transparent;">{cell}</td>' for cell in row
            ) + '</tr>'
        table_html += '</table>'
        st.sidebar.markdown(table_html, unsafe_allow_html=True)
    for league in ['American League', 'National League']:
        st.sidebar.markdown(f"### {league}")
        for division in ['East', 'Central', 'West']:
            entries = division_map[league][division]
            if entries:
                render_division_block_sidebar(division, entries)

    # Main content for Strikeout Tracker
    st.title("MLB Strikeout Tracker — 2025 Season")

    no_game_msgs = []
    if team1_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
        no_game_msgs.append(f"No official MLB games for {pitcher1_name} ({team1_abbr}) before 2025-03-27.")
    if team2_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
        no_game_msgs.append(f"No official MLB games for {pitcher2_name} ({team2_abbr}) before 2025-03-27.")
    if no_game_msgs:
        for msg in no_game_msgs:
            st.warning(msg)

    p1_id, team1_code = pitcher_map[pitcher1_name]
    p2_id, team2_code = pitcher_map[pitcher2_name]
    col1, col2 = st.columns(2)
    logs = {}
    color_map = {pitcher1_name: ROYAL_BLUE, pitcher2_name: ORANGE}
    for col, pid, name, code in [
        (col1, p1_id, pitcher1_name, team1_code),
        (col2, p2_id, pitcher2_name, team2_code)
    ]:
        with col:
            st.subheader(f"{name} ({team_info[code]['name']})")
            st.image(get_player_image(pid), width=100)
            df_k = fetch_k_log(
                pid,
                datetime.combine(start_date, datetime.min.time()),
                end_date,
                code
            )
            logs[name] = df_k
            if df_k.empty:
                st.info("No strikeout data in selected period.")
                continue
            st.dataframe(
                df_k[['K No', 'MM-DD', 'home_team', 'away_team', 'Batter']],
                use_container_width=True)
            chart = (alt.Chart(df_k)
                    .mark_line(point=False, color=color_map[name])
                    .encode(
                        x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
                        y=alt.Y('K No:Q', title='Cumulative Ks', axis=alt.Axis(format='d'))
                    ) +
                    alt.Chart(df_k)
                    .mark_point(size=60, filled=True, color=color_map[name])
                    .encode(x='Date:T', y='K No:Q'))
            st.altair_chart(chart.properties(title=f"{name} Strikeout Pace"), use_container_width=True)

    if all(not logs[n].empty for n in [pitcher1_name, pitcher2_name]):
        st.subheader("Head-to-Head Comparison")
        merged = pd.concat([
            logs[pitcher1_name].assign(Pitcher=player1_name),
            logs[pitcher2_name].assign(Pitcher=player2_name)
        ])
        comparison = (
            alt.Chart(merged)
            .mark_line(point=False)
            .encode(
                x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
                y=alt.Y('K No:Q', title='Cumulative Ks', axis=alt.Axis(format='d')),
                color=alt.Color('Pitcher:N', scale=alt.Scale(
                    domain=[pitcher1_name, pitcher2_name],
                    range=[ROYAL_BLUE, ORANGE])),
                tooltip=['Pitcher', 'Date', 'K No', 'Batter']
            )
            + alt.Chart(merged)
            .mark_point(size=60, filled=True)
            .encode(x='Date:T', y='K No:Q', color='Pitcher:N')
        )
        st.altair_chart(comparison, use_container_width=True)

    st.caption("Game data: Statcast (pybaseball), Rosters: MLB-StatsAPI | News: MLB.com RSS feed")

# --- MLB NEWS: SIDEBAR BOTTOM ---
with st.sidebar:
    st.markdown("---")
    st.markdown("### Latest MLB News")
    news_list = fetch_mlb_news_rss()
    filtered = []
    seen = set()
    for a in news_list:
        if not is_valid_news(a):
            continue
        if a['link'] not in seen:
            filtered.append(a)
            seen.add(a['link'])
        if len(filtered) >= 3:
            break
    if filtered:
        for news in filtered:
            pub = news.get('published', '')
            # pubDate例: "Tue, 02 Jul 2024 00:13:30 GMT"
            try:
                pub_dt_utc = pd.to_datetime(pub).tz_localize('UTC')
                pub_dt_edt = pub_dt_utc.tz_convert('America/New_York')
                pub_fmt = pub_dt_edt.strftime("%Y-%m-%d %H:%M EDT")
            except Exception:
                pub_fmt = pub[:16]
            date_line = f"<span style='font-size:10px;color:#666;'>{pub_fmt}</span>" if pub_fmt else ""
            st.markdown(
                f"- [**{news['title']}**]({news['link']})  {date_line}",
                unsafe_allow_html=True
            )
        st.caption("News from MLB.com RSS | Data updated automatically. All times are shown in EDT (GMT-4).")
    else:
        st.info("No valid MLB news articles found.")
