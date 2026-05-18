import streamlit as st
import pandas as pd
from datetime import date
import io
import psycopg2
import psycopg2.extras
from psycopg2 import IntegrityError as DBIntegrityError
import bcrypt
import json
import requests
import base64
from pathlib import Path

st.set_page_config(page_title="Snake Eyes // D-backs Pitch Intel",page_icon="⚾",layout="wide",initial_sidebar_state="expanded")

def get_db():
    try:
        db_url = st.secrets["DATABASE_URL"]
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn, "pg"
    except Exception:
        import sqlite3
        conn = sqlite3.connect(str(Path.home() / "snake_eyes.db"))
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"

def ph(db_type, n=1):
    """Return correct placeholder — %s for pg, ? for sqlite."""
    return ",".join(["%s" if db_type=="pg" else "?"]*n)

def execute(conn, db_type, sql, params=()):
    sql_conv = sql if db_type=="pg" else sql.replace("%s","?")
    cur = conn.cursor()
    cur.execute(sql_conv, params)
    return cur

def fetchall(conn, db_type, sql, params=()):
    cur = execute(conn, db_type, sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def fetchone(conn, db_type, sql, params=()):
    cur = execute(conn, db_type, sql, params)
    row = cur.fetchone()
    return dict(row) if row else None

def init_db():
    conn, db = get_db()
    serial = "SERIAL" if db=="pg" else "INTEGER"
    auto   = "" if db=="pg" else "AUTOINCREMENT"
    pk     = f"{serial} PRIMARY KEY" if db=="pg" else f"INTEGER PRIMARY KEY {auto}"
    today_fn = "CURRENT_DATE" if db=="pg" else "date('now')"
    execute(conn, db, f"""CREATE TABLE IF NOT EXISTS users (
        id {pk}, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'Scout',
        default_level TEXT DEFAULT 'AAA', created_at TEXT DEFAULT ({today_fn}))""")
    execute(conn, db, f"""CREATE TABLE IF NOT EXISTS tips (
        id {pk}, mlb_player_id INTEGER, name TEXT NOT NULL, jersey_number TEXT,
        hand TEXT NOT NULL, opponent TEXT NOT NULL, level TEXT NOT NULL,
        tip_view TEXT NOT NULL, internal INTEGER NOT NULL DEFAULT 0,
        pitch TEXT NOT NULL, tell_type TEXT NOT NULL, tell TEXT NOT NULL,
        vantage TEXT, confidence TEXT NOT NULL, games INTEGER NOT NULL DEFAULT 1,
        tags TEXT, status TEXT NOT NULL DEFAULT 'pending',
        submitted_by TEXT NOT NULL, submitted_by_display TEXT NOT NULL,
        date_added TEXT NOT NULL, clips TEXT NOT NULL DEFAULT '[]',
        history TEXT NOT NULL DEFAULT '[]')""")
    execute(conn, db, f"""CREATE TABLE IF NOT EXISTS opponents (
        id {pk}, level TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(level,name))""")
    execute(conn, db, f"""CREATE TABLE IF NOT EXISTS team_requests (
        id {pk}, level TEXT NOT NULL, team_name TEXT NOT NULL,
        requested_by TEXT NOT NULL, requested_by_display TEXT NOT NULL,
        date_requested TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        mlb_player_id INTEGER, player_name TEXT)""")
    row = fetchone(conn, db, "SELECT COUNT(*) as cnt FROM users")
    if row["cnt"] == 0:
        pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        execute(conn, db, "INSERT INTO users (username,display_name,password_hash,role,default_level) VALUES (%s,%s,%s,%s,%s)",
                ("admin","Jon Gerber",pw,"Admin","AAA"))
    row = fetchone(conn, db, "SELECT COUNT(*) as cnt FROM opponents")
    if row["cnt"] == 0:
        dops={"MLB":["Atlanta Braves","Baltimore Orioles","Boston Red Sox","Chicago Cubs","Chicago White Sox","Cincinnati Reds","Cleveland Guardians","Colorado Rockies","Detroit Tigers","Houston Astros","Kansas City Royals","Los Angeles Angels","Los Angeles Dodgers","Miami Marlins","Milwaukee Brewers","Minnesota Twins","New York Mets","New York Yankees","Oakland Athletics","Philadelphia Phillies","Pittsburgh Pirates","San Diego Padres","San Francisco Giants","Seattle Mariners","St. Louis Cardinals","Tampa Bay Rays","Texas Rangers","Toronto Blue Jays","Washington Nationals"],"AAA":["Albuquerque Isotopes (COL)","El Paso Chihuahuas (SD)","Las Vegas Aviators (OAK)","Oklahoma City Comets (LAD)","Round Rock Express (TEX)","Sacramento River Cats (SF)","Salt Lake Bees (LAA)","Sugar Land Space Cowboys (HOU)","Tacoma Rainiers (SEA)"],"AA":["Arkansas Travelers (SEA)","Corpus Christi Hooks (HOU)","Frisco RoughRiders (TEX)","Midland RockHounds (OAK)","NW Arkansas Naturals (KC)","San Antonio Missions (SD)","Springfield Cardinals (STL)","Tulsa Drillers (LAD)","Wichita Wind Surge (MIN)"],"A+":["Eugene Emeralds (SF)","Everett AquaSox (SEA)","Spokane Indians (COL)","Tri-City Dust Devils (LAA)","Vancouver Canadians (TOR)"],"A":["Fresno Grizzlies (COL)","Lake Elsinore Storm (SD)","Ontario Tower Buzzers (SEA)","Rancho Cucamonga Quakes (LAA)","San Bernardino IE 66ers (SEA)","San Jose Giants (SF)","Stockton Ports (OAK)"],"ACL":["ACL Angels","ACL Astros","ACL Athletics","ACL Blue Jays","ACL Brewers","ACL Cardinals","ACL Cubs","ACL Dodgers","ACL Giants","ACL Guardians","ACL Mariners","ACL Padres","ACL Rangers","ACL Rays","ACL Red Sox","ACL Rockies","ACL Royals","ACL Tigers","ACL Twins","ACL White Sox","ACL Yankees"]}
        for lvl,opps in dops.items():
            for opp in opps:
                try: execute(conn, db, "INSERT INTO opponents (level,name) VALUES (%s,%s)",(lvl,opp))
                except: pass
    conn.commit(); conn.close()

init_db()

def get_db_tips(level=None,opponent=None,tip_view=None,internal=None,status=None,name=None):
    conn,db=get_db(); q="SELECT * FROM tips WHERE 1=1"; p=[]
    if level:    q+=" AND level=%s";    p.append(level)
    if opponent: q+=" AND opponent=%s"; p.append(opponent)
    if tip_view: q+=" AND tip_view=%s"; p.append(tip_view)
    if internal is not None: q+=" AND internal=%s"; p.append(1 if internal else 0)
    if status:   q+=" AND status=%s";   p.append(status)
    if name:     q+=" AND LOWER(name)=%s"; p.append(name.lower())
    q+=" ORDER BY date_added DESC"
    rows=fetchall(conn,db,q,p); conn.close()
    for d in rows:
        d["clips"]=json.loads(d["clips"] or "[]"); d["history"]=json.loads(d["history"] or "[]"); d["internal"]=bool(d["internal"])
    return rows

def get_db_tip(tid):
    conn,db=get_db(); row=fetchone(conn,db,"SELECT * FROM tips WHERE id=%s",(tid,)); conn.close()
    if not row: return None
    row["clips"]=json.loads(row["clips"] or "[]"); row["history"]=json.loads(row["history"] or "[]"); row["internal"]=bool(row["internal"]); return row

def add_db_tip(tip):
    conn,db=get_db()
    execute(conn,db,"INSERT INTO tips (mlb_player_id,name,jersey_number,hand,opponent,level,tip_view,internal,pitch,tell_type,tell,vantage,confidence,games,tags,status,submitted_by,submitted_by_display,date_added,clips,history) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tip.get("mlb_player_id"),tip["name"],tip.get("jersey_number",""),tip["hand"],tip["opponent"],tip["level"],tip["tip_view"],1 if tip.get("internal") else 0,tip["pitch"],tip["tell_type"],tip["tell"],tip.get("vantage",""),tip["confidence"],tip["games"],tip.get("tags",""),tip.get("status","pending"),tip["submitted_by"],tip["submitted_by_display"],tip["date_added"],json.dumps(tip.get("clips",[])),json.dumps(tip.get("history",[]))))
    conn.commit(); conn.close()

def update_db_tip(tid,fields):
    if "clips"   in fields: fields["clips"]  =json.dumps(fields["clips"])
    if "history" in fields: fields["history"]=json.dumps(fields["history"])
    if "internal" in fields: fields["internal"]=1 if fields["internal"] else 0
    conn,db=get_db()
    set_clause=", ".join(f"{k}=%s" for k in fields)
    execute(conn,db,f"UPDATE tips SET {set_clause} WHERE id=%s",list(fields.values())+[tid])
    conn.commit(); conn.close()

def get_db_opponents(level=None):
    conn,db=get_db()
    rows=fetchall(conn,db,"SELECT name FROM opponents WHERE level=%s ORDER BY name",(level,)) if level else fetchall(conn,db,"SELECT level,name FROM opponents ORDER BY level,name")
    conn.close(); return rows

def add_db_opponent(level,name):
    conn,db=get_db()
    try: execute(conn,db,"INSERT INTO opponents (level,name) VALUES (%s,%s)",(level,name)); conn.commit(); conn.close(); return True
    except: conn.close(); return False

def del_db_opponent(level,name):
    conn,db=get_db(); execute(conn,db,"DELETE FROM opponents WHERE level=%s AND name=%s",(level,name)); conn.commit(); conn.close()

def get_db_users():
    conn,db=get_db(); rows=fetchall(conn,db,"SELECT id,username,display_name,role,default_level,created_at FROM users ORDER BY id"); conn.close(); return rows

def add_db_user(username,display_name,password,role,default_level):
    pw_hash=bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()
    conn,db=get_db()
    try: execute(conn,db,"INSERT INTO users (username,display_name,password_hash,role,default_level) VALUES (%s,%s,%s,%s,%s)",(username.lower().strip(),display_name.strip(),pw_hash,role,default_level)); conn.commit(); conn.close(); return True,"User created."
    except: conn.close(); return False,"Username already exists."

def update_db_user(uid,display_name,role,default_level):
    conn,db=get_db(); execute(conn,db,"UPDATE users SET display_name=%s,role=%s,default_level=%s WHERE id=%s",(display_name.strip(),role,default_level,uid)); conn.commit(); conn.close()

def del_db_user(uid):
    conn,db=get_db(); execute(conn,db,"DELETE FROM users WHERE id=%s",(uid,)); conn.commit(); conn.close()

def del_db_tip(tid):
    conn,db=get_db(); execute(conn,db,"DELETE FROM tips WHERE id=%s",(tid,)); conn.commit(); conn.close()

def check_db_login(username,password):
    conn,db=get_db(); row=fetchone(conn,db,"SELECT * FROM users WHERE username=%s",(username.lower().strip(),)); conn.close()
    if not row: return None
    return row if bcrypt.checkpw(password.encode(),row["password_hash"].encode()) else None

def update_db_password(uid,new_password):
    pw_hash=bcrypt.hashpw(new_password.encode(),bcrypt.gensalt()).decode()
    conn,db=get_db(); execute(conn,db,"UPDATE users SET password_hash=%s WHERE id=%s",(pw_hash,uid)); conn.commit(); conn.close()

def get_team_requests(status=None):
    conn,db=get_db()
    q="SELECT * FROM team_requests"+(f" WHERE status=%s" if status else "")+" ORDER BY date_requested DESC"
    rows=fetchall(conn,db,q,(status,) if status else ()); conn.close(); return rows

def add_team_request(level,team_name,req_by,req_by_display,pid,pname):
    conn,db=get_db(); execute(conn,db,"INSERT INTO team_requests (level,team_name,requested_by,requested_by_display,date_requested,status,mlb_player_id,player_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",(level,team_name,req_by,req_by_display,str(date.today()),"pending",pid,pname)); conn.commit(); conn.close()

def resolve_team_request(rid,approve,level,team_name):
    conn,db=get_db(); execute(conn,db,"UPDATE team_requests SET status=%s WHERE id=%s",("approved" if approve else "rejected",rid)); conn.commit(); conn.close()
    if approve: add_db_opponent(level,team_name)


def search_mlb_players(query):
    try:
        r=requests.get("https://statsapi.mlb.com/api/v1/people/search",params={"names":query,"sportIds":"1,11,12,13,14,16","hydrate":"currentTeam"},timeout=6)
        out=[]
        for p in r.json().get("people",[]):
            pos=p.get("primaryPosition",{}).get("abbreviation","")
            if pos not in ("P","SP","RP","CL"): continue
            team=p.get("currentTeam",{})
            out.append({"id":p.get("id"),"name":p.get("fullName",""),"jersey":p.get("primaryNumber","—"),"hand":p.get("pitchHand",{}).get("code","R")+"HP","team":team.get("name","Unknown"),"team_id":team.get("id"),"level":{1:"MLB",11:"AAA",12:"AA",13:"A+",14:"A",16:"ACL"}.get(p.get("sport",{}).get("id"),"MiLB")})
        return out
    except: return []

def find_opp_match(team_name, level):
    """Try to match team name to opponent list. If level is unknown, search all levels."""
    search_levels = [level] if level in ORG else list(ORG.keys())
    team_lower = team_name.lower().strip()
    for lvl in search_levels:
        opps = [r["name"] for r in get_db_opponents(lvl)]
        for opp in opps:
            opp_base = opp.split(" (")[0].lower().strip()
            if team_lower == opp_base: return opp, lvl
            if team_lower in opp_base: return opp, lvl
            if opp_base in team_lower: return opp, lvl
        # Word-level fallback
        team_words = [w for w in team_lower.split() if len(w) > 3]
        for opp in opps:
            opp_base = opp.split(" (")[0].lower()
            if any(w in opp_base for w in team_words): return opp, lvl
    return None, level

@st.cache_data(ttl=1800)
def fetch_today_schedule():
    from datetime import date as dt
    today=dt.today().strftime("%Y-%m-%d")
    SRCH={"MLB":"Arizona Diamondbacks","AAA":"Reno","AA":"Amarillo","A+":"Hillsboro","A":"Visalia","ACL":"ACL D-backs"}
    try:
        r=requests.get("https://statsapi.mlb.com/api/v1/teams",params={"sportIds":"1,11,12,13,14,16","season":today[:4]},timeout=8)
        teams=r.json().get("teams",[])
    except: return {}
    aff_ids={}
    for lvl,search in SRCH.items():
        for team in teams:
            if search.lower() in team.get("name","").lower(): aff_ids[lvl]={"id":team["id"]}; break
    try:
        r2=requests.get("https://statsapi.mlb.com/api/v1/schedule",params={"date":today,"sportId":"1,11,12,13,14,16","hydrate":"team"},timeout=8)
        games=[]
        for de in r2.json().get("dates",[]): games.extend(de.get("games",[]))
    except: return {}
    results={}
    for lvl,aff in aff_ids.items():
        for game in games:
            away_id=game.get("teams",{}).get("away",{}).get("team",{}).get("id")
            home_id=game.get("teams",{}).get("home",{}).get("team",{}).get("id")
            away_name=game.get("teams",{}).get("away",{}).get("team",{}).get("name","")
            home_name=game.get("teams",{}).get("home",{}).get("team",{}).get("name","")
            if aff["id"] in (away_id,home_id):
                results[lvl]={"opponent":home_name if away_id==aff["id"] else away_name,"status":game.get("status",{}).get("detailedState",""),"home":home_id==aff["id"]}; break
    return results

ORG={"MLB":{"affiliate":"Arizona Diamondbacks","league":"National League West"},"AAA":{"affiliate":"Reno Aces","league":"Pacific Coast League"},"AA":{"affiliate":"Amarillo Sod Poodles","league":"Texas League"},"A+":{"affiliate":"Hillsboro Hops","league":"Northwest League"},"A":{"affiliate":"Visalia Rawhide","league":"California League"},"ACL":{"affiliate":"ACL D-backs","league":"Arizona Complex League"}}
OWN_AFFILIATES={lvl:d["affiliate"] for lvl,d in ORG.items()}
LEVEL_COLORS={"MLB":"#5a4a38","AAA":"#5a4a90","AA":"#2a6090","A+":"#2a7840","A":"#906020","ACL":"#c8341a"}
LEVEL_ORDER=["MLB","AAA","AA","A+","A","ACL"]
TIP_VIEWS=["Pitcher — Home Plate View","Pitcher — 2B View","Catcher Tips"]
AFF_DISPLAY={"MLB":("Arizona","Diamondbacks"),"AAA":("Reno","Aces"),"AA":("Amarillo","Sod Poodles"),"A+":("Hillsboro","Hops"),"A":("Visalia","Rawhide"),"ACL":("ACL","D-backs")}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'IBM Plex Sans',sans-serif;background-color:#f0e8d8;color:#1a1410;}
.stApp{background-color:#f0e8d8;}
section[data-testid="stSidebar"]{background-color:#e8dcc8;border-right:1px solid #c8b898;}
section[data-testid="stSidebar"] .stButton>button{background:transparent;border:none;color:#5a4a38;text-align:left;font-size:13px;padding:7px 10px;border-radius:5px;border-left:2px solid transparent;width:100%;}
section[data-testid="stSidebar"] .stButton>button:hover{background:#ddd0b8;color:#1a1410;border-left-color:#c8341a;}
section[data-testid="stSidebar"] div[data-testid="column"] .stButton>button{background-color:#e8dcc8!important;border:1px solid #e8dcc8!important;color:#9a8a78!important;font-size:16px!important;padding:4px 8px!important;border-radius:5px!important;box-shadow:none!important;}
section[data-testid="stSidebar"] div[data-testid="column"] .stButton>button:hover{background-color:#ddd0b8!important;border-color:#ddd0b8!important;color:#1a1410!important;}
.stButton>button{background-color:#e8dcc8;color:#3a2a1a;border:1px solid #c8b898;border-radius:6px;font-family:'IBM Plex Sans',sans-serif;transition:all .15s;}
.stButton>button:hover{border-color:#c8341a;color:#c8341a;background-color:#ecdfc9;}
.stButton>button[kind="primary"]{background:#c8341a!important;color:#fff!important;border-color:#c8341a!important;font-weight:600!important;}
.stButton>button[kind="primary"]:hover{background:#a82a14!important;}
.stTextInput>div>div>input,.stTextArea>div>div>textarea,.stSelectbox>div>div,.stNumberInput>div>div>input{background-color:#ede3d0!important;color:#1a1410!important;border:1px solid #c8b898!important;border-radius:6px!important;}
div[data-testid="stMetricValue"]{color:#1a1410!important;font-size:28px!important;font-weight:600;}
div[data-testid="stMetricLabel"]{color:#7a6a58!important;font-family:'IBM Plex Mono',monospace!important;font-size:10px!important;letter-spacing:.1em;text-transform:uppercase;}
.stTabs [data-baseweb="tab-list"]{background-color:#e8dcc8;border-radius:8px;padding:4px;gap:4px;border:1px solid #c8b898;}
.stTabs [data-baseweb="tab"]{background-color:transparent;border-radius:6px;color:#7a6a58;font-size:13px;font-weight:500;padding:8px 16px;border:none;}
.stTabs [data-baseweb="tab"]:hover{color:#1a1410;background-color:#ddd0b8;}
.stTabs [aria-selected="true"]{background-color:#c8341a!important;color:#fff!important;}
.stTabs [data-baseweb="tab-panel"]{padding-top:20px;}
.stRadio>div{flex-direction:row;gap:16px;}
.home-hero{background:linear-gradient(135deg,#2a1a10 0%,#4a2010 50%,#3a1808 100%);border-radius:12px;padding:36px 40px;margin-bottom:28px;}
.home-hero-tag{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#c8341a;letter-spacing:.2em;text-transform:uppercase;margin-bottom:10px;}
.home-hero-title{font-size:32px;font-weight:600;color:#f0e8d8;margin-bottom:6px;}
.home-hero-sub{font-size:14px;color:#a89880;font-family:'IBM Plex Mono',monospace;}
.stat-card{background:#e8dcc8;border:1px solid #c8b898;border-radius:10px;padding:16px 18px;text-align:center;}
.stat-card-value{font-size:30px;font-weight:600;color:#1a1410;line-height:1;margin-bottom:6px;}
.stat-card-label{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#7a6a58;letter-spacing:.1em;text-transform:uppercase;}
.level-card{background:#e8dcc8;border:1px solid #c8b898;border-radius:10px;padding:18px 20px;margin-bottom:10px;}
.level-card:hover{border-color:#c8341a;background:#ede3d0;}
.level-card-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;}
.level-card-title{font-size:17px;font-weight:600;color:#1a1410;}
.level-card-affiliate{font-size:13px;color:#7a6a58;font-family:'IBM Plex Mono',monospace;margin-top:2px;}
.level-card-count{font-size:28px;font-weight:600;color:#c8341a;font-family:'IBM Plex Mono',monospace;line-height:1;}
.level-card-count.zero{color:#c8b898;}
.level-stat{font-size:12px;color:#7a6a58;display:inline-block;margin-right:20px;}
.level-stat strong{color:#1a1410;font-weight:600;}
.level-divider{border:none;border-top:1px solid #d8ccb8;margin:10px 0;}
.opponent-card{background:#e8dcc8;border:1px solid #c8b898;border-radius:8px;padding:12px 16px;margin-bottom:6px;display:flex;align-items:center;justify-content:space-between;}
.opponent-card:hover{border-color:#c8341a;background:#ede3d0;}
.opponent-name{font-size:14px;font-weight:500;color:#1a1410;}
.opponent-meta{font-size:11px;color:#7a6a58;font-family:'IBM Plex Mono',monospace;margin-top:2px;}
.opp-count{font-size:14px;font-weight:600;color:#c8341a;font-family:'IBM Plex Mono',monospace;}
.opp-count.zero{color:#c8b898;}
.pitcher-card{background:#e8dcc8;border:1px solid #c8b898;border-radius:8px;padding:14px 16px;margin-bottom:8px;}
.pitcher-card:hover{background:#ede3d0;}
.pitcher-card.high{border-left:3px solid #2a7a40;}
.pitcher-card.medium{border-left:3px solid #c87820;}
.pitcher-card.low{border-left:3px solid #c8341a;}
.pitcher-card.pending{border-left:3px solid #c87820;border-color:#c8782044;}
.pitcher-card.inactive{border-left:3px solid #c8b898;opacity:0.7;}
.pitcher-name-lg{font-size:15px;font-weight:600;color:#1a1410;}
.tell-preview{font-size:13px;color:#5a4a38;margin:5px 0;line-height:1.55;}
.tell-preview strong{color:#2a1a10;}
.clip-meta{font-size:11px;color:#9a8a78;font-family:'IBM Plex Mono',monospace;}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:500;font-family:'IBM Plex Mono',monospace;margin-right:3px;}
.b-mlb{background:#2a1a1022;color:#5a4a38;border:1px solid #2a1a1040;}
.b-aaa{background:#2a1a5022;color:#5a4a90;border:1px solid #2a1a5040;}
.b-aa{background:#0a2a4822;color:#2a6090;border:1px solid #0a2a4840;}
.b-aplus{background:#0a3a1822;color:#2a7840;border:1px solid #0a3a1840;}
.b-a{background:#3a200022;color:#906020;border:1px solid #3a200040;}
.b-acl{background:#3a100022;color:#c8341a;border:1px solid #3a100040;}
.b-team{background:#d8ccb8;color:#7a6a58;border:1px solid #c8b898;}
.b-pend{background:#3a200022;color:#c87820;border:1px solid #3a200040;}
.b-active{background:#0a3a1822;color:#2a7840;border:1px solid #0a3a1840;}
.b-high{background:#0a3a1822;color:#2a7840;border:1px solid #0a3a1840;}
.b-med{background:#3a200022;color:#c87820;border:1px solid #3a200040;}
.b-low{background:#3a100022;color:#c8341a;border:1px solid #3a100040;}
.b-inactive{background:#d8ccb8;color:#9a8a78;border:1px solid #c8b898;}
.b-hp{background:#1a2a4822;color:#2a5090;border:1px solid #1a2a4840;}
.b-2b{background:#1a3a2822;color:#2a6840;border:1px solid #1a3a2840;}
.b-cat{background:#3a1a1022;color:#906030;border:1px solid #3a1a1040;}
.section-title{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a8a78;letter-spacing:.14em;text-transform:uppercase;margin-bottom:12px;margin-top:4px;}
.breadcrumb{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#9a8a78;margin-bottom:16px;}
.breadcrumb .current{color:#1a1410;font-weight:500;}
.detail-section{background:#e8dcc8;border:1px solid #c8b898;border-radius:8px;padding:14px;margin-bottom:12px;}
.detail-label{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a8a78;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px;}
.video-box{background:#2a1a10;border:1px solid #3a2a1a;border-radius:8px;padding:36px 20px;text-align:center;margin-bottom:12px;}
.queue-card{background:#e8dcc8;border:1px solid #c8782044;border-left:3px solid #c87820;border-radius:8px;overflow:hidden;margin-bottom:10px;}
.queue-header{background:#c8782012;padding:10px 14px;}
.queue-title{font-size:13px;font-weight:600;color:#c87820;}
.queue-body{padding:12px 14px;}
.connect-card{background:#e8dcc8;border:1px solid #c8b898;border-radius:10px;padding:20px;margin-bottom:12px;}
.search-result{background:#e8dcc8;border:1px solid #c8b898;border-radius:8px;padding:12px 16px;margin-bottom:6px;}
.search-result:hover{border-color:#c8341a;background:#ede3d0;}
.history-entry{background:#e8dcc8;border:1px solid #c8b898;border-radius:6px;padding:10px 14px;margin-bottom:6px;}
.history-date{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a8a78;}
.empty-tab{background:#e8dcc8;border:1px dashed #c8b898;border-radius:8px;padding:40px;text-align:center;}
.player-result{background:#e8dcc8;border:1px solid #c8b898;border-radius:6px;padding:10px 14px;margin-bottom:6px;}
.player-selected{background:#c8341a12;border:1px solid #c8341a44;border-radius:8px;padding:12px 16px;margin:12px 0;}
.locked-field{background:#ddd0b8;border:1px solid #c8b898;border-radius:6px;padding:8px 12px;font-size:13px;color:#5a4a38;margin-bottom:8px;}
.locked-label{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a8a78;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;}
.team-request-card{background:#e8dcc8;border:1px solid #c8341a44;border-left:3px solid #c8341a;border-radius:8px;padding:14px;margin-bottom:8px;}
.media-slot{background:#e8dcc8;border:1px solid #c8b898;border-radius:8px;padding:14px;margin-bottom:8px;}
hr{border-color:#c8b898!important;}
::-webkit-scrollbar{width:5px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:#c8b898;border-radius:3px;}
</style>
""", unsafe_allow_html=True)

for k,v in {"user":None,"page":"home","selected_level":None,"selected_opponent":None,"selected_tip_id":None,"selected_pitcher":None,"active_clip":0,"prefill_level":None,"prefill_opponent":None,"prefill_internal":False,"show_inactive_tips":False,"editing_tip_id":None,"video_connections":{"PitchBase":False,"TruMedia":False},"selected_player":None,"media_rows":[{"type":"video"}]}.items():
    if k not in st.session_state: st.session_state[k]=v

def go(page,level=None,opponent=None,tip_id=None,pitcher=None):
    st.session_state.page=page
    if level:    st.session_state.selected_level=level
    if opponent: st.session_state.selected_opponent=opponent
    if tip_id:   st.session_state.selected_tip_id=tip_id
    if pitcher:  st.session_state.selected_pitcher=pitcher
    st.session_state.active_clip=0
    st.rerun()

def opp_short(opp): return opp.split(" (")[0] if " (" in opp else opp
def level_badge(l):
    cls={"MLB":"b-mlb","AAA":"b-aaa","AA":"b-aa","A+":"b-aplus","A":"b-a","ACL":"b-acl"}.get(l,"b-team")
    return f'<span class="badge {cls}">{l}</span>'
def conf_badge(c):
    cls={"High":"b-high","Medium":"b-med","Low":"b-low"}.get(c,"b-team")
    return f'<span class="badge {cls}">{c}</span>'
def status_badge(s):
    if s=="active": return '<span class="badge b-active">active</span>'
    if s=="pending": return '<span class="badge b-pend">pending</span>'
    return '<span class="badge b-inactive">inactive</span>'
def view_badge(v):
    if "Home Plate" in v: return '<span class="badge b-hp">Home Plate</span>'
    if "2B" in v: return '<span class="badge b-2b">2B View</span>'
    if "Catcher" in v: return '<span class="badge b-cat">Catcher</span>'
    return ''
def current_user(): return st.session_state.user
def require_login(): return st.session_state.user is not None
def is_admin(): u=current_user(); return u and u["role"]=="Admin"

def render_pitcher_card(tip):
    tags=" ".join([f'<span style="font-size:11px;padding:1px 7px;border-radius:99px;background:#d8ccb8;color:#7a6a58;border:1px solid #c8b898;">{t.strip()}</span>' for t in (tip.get("tags") or "").split(",") if t.strip()])
    bc={"High":"high","Medium":"medium","Low":"low"}.get(tip["confidence"],"medium")
    if tip["status"]=="pending": bc="pending"
    if tip["status"]=="inactive": bc="inactive"
    jersey=f'#{tip["jersey_number"]}' if tip.get("jersey_number") and tip["jersey_number"] not in ("—","") else ""
    pid=f'ID:{tip["mlb_player_id"]}' if tip.get("mlb_player_id") else ""
    id_badge=f'<span style="font-size:10px;padding:1px 6px;border-radius:4px;background:#d8ccb8;color:#9a8a78;font-family:monospace;margin-right:4px;">{pid}</span>' if pid else ""
    jersey_badge=f'<span style="font-size:11px;font-weight:600;color:#7a6a58;margin-right:4px;">{jersey}</span>' if jersey else ""
    clips=tip.get("clips",[])
    vids=len([c for c in clips if c.get("clip_type","video")=="video"])
    imgs=len([c for c in clips if c.get("clip_type","video")=="image"])
    parts=[]
    if vids: parts.append(f"{vids} video{'s' if vids!=1 else ''}")
    if imgs: parts.append(f"{imgs} image{'s' if imgs!=1 else ''}")
    media_str=" · ".join(parts) if parts else "no media"
    st.markdown(f"""
    <div class="pitcher-card {bc}">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px;">
            {jersey_badge}<span class="pitcher-name-lg">{tip['name']}</span>{id_badge}
            <span class="badge b-team">{tip['hand']}</span>{level_badge(tip['level'])}
            <span class="badge b-team">{opp_short(tip.get('opponent',''))}</span>
            {view_badge(tip.get('tip_view',''))}{status_badge(tip['status'])} {conf_badge(tip['confidence'])}
        </div>
        <div class="tell-preview"><strong>{tip['tell_type']}:</strong> {tip['tell'][:130]}{'...' if len(tip['tell'])>130 else ''}</div>
        <div style="margin-bottom:5px;">{tags}</div>
        <div class="clip-meta">{media_str} · {tip['games']} game{'s' if tip['games']!=1 else ''} sampled · {tip['date_added']} · {tip['submitted_by_display']}</div>
    </div>""", unsafe_allow_html=True)

def render_tips_in_view(tips_list,key_prefix):
    if not tips_list:
        st.markdown('<div class="empty-tab"><div style="font-size:14px;color:#7a6a58;">No tips in this category yet</div></div>',unsafe_allow_html=True)
    else:
        for tip in tips_list:
            render_pitcher_card(tip)
            c1,c2,c3=st.columns(3)
            with c1:
                if st.button("View tip →",key=f"{key_prefix}_vt_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
            with c2:
                if st.button("Edit",key=f"{key_prefix}_ed_{tip['id']}"): st.session_state.editing_tip_id=tip["id"]; go("edit_tip")
            with c3:
                if st.button("Pitcher →",key=f"{key_prefix}_vp_{tip['id']}"): go("pitcher_profile",pitcher=tip["name"])

def generate_series_pdf(level,opponent,selected_tips,report_date):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,HRFlowable
        from reportlab.lib.enums import TA_CENTER
        buf=io.BytesIO()
        doc=SimpleDocTemplate(buf,pagesize=letter,leftMargin=0.75*inch,rightMargin=0.75*inch,topMargin=0.75*inch,bottomMargin=0.75*inch)
        dark=colors.HexColor("#1a1410");red=colors.HexColor("#c8341a");mid=colors.HexColor("#7a6a58");light=colors.HexColor("#e8dcc8");green=colors.HexColor("#2a7840");amber=colors.HexColor("#c87820")
        def sty(n,**kw): return ParagraphStyle(n,**kw)
        story=[]
        story.append(Paragraph("SNAKE EYES",sty("logo",fontName="Helvetica-Bold",fontSize=10,textColor=red,spaceAfter=6)))
        story.append(Paragraph(f"Series Prep — {opp_short(opponent)}",sty("title",fontName="Helvetica-Bold",fontSize=22,textColor=dark,spaceAfter=4)))
        story.append(Paragraph(f"{level} · {ORG[level]['affiliate']} · {report_date}",sty("sub",fontName="Helvetica",fontSize=11,textColor=mid,spaceAfter=2)))
        story.append(Spacer(1,6));story.append(HRFlowable(width="100%",thickness=2,color=red,spaceAfter=16))
        for view in TIP_VIEWS:
            vt=[t for t in selected_tips if t.get("tip_view","")==view]
            if not vt: continue
            story.append(Paragraph(view.upper(),sty("vh",fontName="Helvetica-Bold",fontSize=10,textColor=red,spaceAfter=6)))
            story.append(HRFlowable(width="100%",thickness=0.5,color=red,spaceAfter=10))
            for tip in vt:
                jersey=f"#{tip['jersey_number']} " if tip.get("jersey_number") and tip["jersey_number"] not in ("—","") else ""
                pid=f"ID:{tip['mlb_player_id']}" if tip.get("mlb_player_id") else ""
                cs=sty("cs",fontName="Helvetica-Bold",fontSize=9,textColor=green if tip["confidence"]=="High" else amber if tip["confidence"]=="Medium" else red)
                tbl=Table([[Paragraph(f"{jersey}{tip['name']}",sty("p",fontName="Helvetica-Bold",fontSize=14,textColor=dark,spaceAfter=4)),Paragraph(f"{tip['hand']} {tip['pitch']} {pid}",sty("n",fontName="Helvetica-Oblique",fontSize=9,textColor=mid,spaceAfter=2)),Paragraph(tip["confidence"].upper(),cs)]],colWidths=[3*inch,2.5*inch,1.5*inch])
                tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),light),("ROWPADDING",(0,0),(-1,-1),8),("LEFTPADDING",(0,0),(0,-1),10),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEBELOW",(0,0),(-1,-1),1,red)]))
                story.append(tbl);story.append(Spacer(1,6))
                story.append(Paragraph(f"<b>Tell ({tip['tell_type']}):</b>",sty("lbl",fontName="Helvetica-Bold",fontSize=8,textColor=mid,spaceAfter=2,leading=10)))
                story.append(Paragraph(tip["tell"],sty("tell",fontName="Helvetica",fontSize=10,textColor=dark,spaceAfter=4,leading=14)))
                if tip.get("vantage"): story.append(Paragraph(f"<b>Vantage:</b> {tip['vantage']}",sty("note",fontName="Helvetica-Oblique",fontSize=9,textColor=mid,spaceAfter=2)))
                clips=tip.get("clips",[])
                vids=[c for c in clips if c.get("clip_type","video")=="video"]
                imgs=[c for c in clips if c.get("clip_type","video")=="image"]
                if vids:
                    story.append(Paragraph(f"<b>Video ({len(vids)}):</b>",sty("lv",fontName="Helvetica-Bold",fontSize=8,textColor=mid,spaceAfter=2,leading=10)))
                    for c in vids: story.append(Paragraph(f"• {c['label']} — {c.get('source','')}: {c.get('url','')}",sty("nv",fontName="Helvetica-Oblique",fontSize=9,textColor=mid,spaceAfter=2)))
                if imgs: story.append(Paragraph(f"<b>Images attached:</b> {len(imgs)}",sty("ni",fontName="Helvetica-Oblique",fontSize=9,textColor=mid,spaceAfter=2)))
                story.append(Spacer(1,16));story.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#d8ccb8"),spaceAfter=16))
        story.append(Spacer(1,12))
        story.append(Paragraph("CONFIDENTIAL — Arizona Diamondbacks Internal Use Only",sty("foot",fontName="Helvetica-Oblique",fontSize=8,textColor=mid,alignment=TA_CENTER)))
        doc.build(story);buf.seek(0);return buf
    except ImportError: return None

# ── LOGIN ────────────────────────────────────────────────────────────────────────
if not require_login():
    col1,col2,col3=st.columns([1,2,1])
    with col2:
        st.markdown('<div style="margin-top:60px;background:#e8dcc8;border:1px solid #c8b898;border-radius:12px;padding:36px;">',unsafe_allow_html=True)
        st.markdown('<div style="font-size:22px;font-weight:600;color:#1a1410;margin-bottom:2px;">Snake Eyes</div><div style="font-size:11px;color:#9a8a78;font-family:monospace;letter-spacing:.1em;margin-bottom:24px;">ARIZONA DIAMONDBACKS // PITCH INTELLIGENCE</div>',unsafe_allow_html=True)
        username=st.text_input("Username"); password=st.text_input("Password",type="password")
        if st.button("Sign In",type="primary",use_container_width=True):
            user=check_db_login(username,password)
            if user: st.session_state.user=user; st.rerun()
            else: st.error("Incorrect username or password.")
        st.markdown('</div>',unsafe_allow_html=True)
    st.stop()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────────
user=current_user()
with st.sidebar:
    ic1,ic2,ic_space=st.columns([1,1,3])
    with ic1:
        if st.button("⌂",key="icon_home",help="Home",use_container_width=True): go("home")
    with ic2:
        if st.button("⌕",key="icon_search",help="Search",use_container_width=True): go("search")
    st.markdown(f'<div style="padding:6px 4px 16px;"><div style="font-family:\'IBM Plex Mono\',monospace;font-size:15px;font-weight:600;color:#c8341a;letter-spacing:.06em;">Snake Eyes</div><div style="font-family:\'IBM Plex Mono\',monospace;font-size:9px;color:#9a8a78;letter-spacing:.12em;margin-top:2px;">ARIZONA DIAMONDBACKS</div></div>',unsafe_allow_html=True)
    st.markdown('<div style="font-family:monospace;font-size:10px;color:#9a8a78;letter-spacing:.12em;text-transform:uppercase;padding:0 4px;margin-bottom:6px;">Org Levels</div>',unsafe_allow_html=True)
    for lvl,data in ORG.items():
        tc=len(get_db_tips(level=lvl,internal=False,status="active")); color=LEVEL_COLORS[lvl]
        is_act=st.session_state.page=="level" and st.session_state.selected_level==lvl
        bg="#ddd0b8" if is_act else "transparent"; bc="#c8341a" if is_act else "transparent"; txt="#1a1410" if is_act else "#5a4a38"
        st.markdown(f'<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-radius:6px;background:{bg};border-left:2px solid {bc};margin-bottom:2px;"><div><span style="font-size:12px;font-weight:600;color:{txt};">{lvl}</span><span style="font-size:11px;color:#9a8a78;margin-left:6px;font-family:monospace;">{data["affiliate"]}</span></div><span style="font-size:11px;color:{color};font-family:monospace;font-weight:600;">{tc if tc else "—"}</span></div>',unsafe_allow_html=True)
        if st.button(f"Open {lvl}",key=f"sn_{lvl}",use_container_width=True): go("level",level=lvl)
    st.markdown('<hr>',unsafe_allow_html=True)
    pc=len(get_db_tips(status="pending")); tr=len(get_team_requests(status="pending"))
    for label,pg in [("All Tips","all_tips"),(f"Pending{f' ({pc})' if pc else ''}","queue"),(f"Team Requests{f' ({tr})' if tr else ''}","team_requests"),("Series Prep","series_prep"),("Video Sources","video"),("My Account","account"),("Admin","admin")]:
        if st.button(label,key=f"nav_{pg}",use_container_width=True): go(pg)
    st.markdown('<hr>',unsafe_allow_html=True)
    st.markdown(f'<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;"><div style="width:30px;height:30px;border-radius:50%;background:#c8341a22;border:1px solid #c8341a44;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#c8341a;text-align:center;line-height:30px;flex-shrink:0;">{user["display_name"][:2].upper()}</div><div><div style="font-size:12px;color:#1a1410;font-weight:500;">{user["display_name"]}</div><div style="font-size:10px;color:#9a8a78;font-family:monospace;">{user["role"]}</div></div></div>',unsafe_allow_html=True)
    if st.button("Sign out",key="signout"): st.session_state.user=None; st.session_state.page="home"; st.rerun()

page=st.session_state.page

# ── HOME ──────────────────────────────────────────────────────────────────────────
if page=="home":
    all_act=get_db_tips(status="active",internal=False); int_tips=get_db_tips(status="active",internal=True)
    st.markdown(f'<div class="home-hero"><div class="home-hero-tag">Arizona Diamondbacks // Pitch Intelligence</div><div class="home-hero-title">Snake Eyes</div><div class="home-hero-sub">Org-wide pitch tipping database · {len(all_act)} active tips across all affiliates</div></div>',unsafe_allow_html=True)
    ht1,ht2=st.tabs(["Opponent Intelligence","Internal Player Tracker"])
    with ht1:
        st.markdown('<div class="section-title">// TODAY\'S GAMES</div>',unsafe_allow_html=True)
        tg=fetch_today_schedule(); pill_cols=st.columns(6)
        for i,lvl in enumerate(["MLB","AAA","AA","A+","A","ACL"]):
            color=LEVEL_COLORS[lvl]; al1,al2=AFF_DISPLAY[lvl]
            with pill_cols[i]:
                if lvl in tg:
                    g=tg[lvl]; opp=opp_short(g["opponent"]); op=opp.rsplit(" ",1); ol1=op[0] if len(op)>1 else opp; ol2=op[1] if len(op)>1 else ""
                    opps_list=[r["name"] for r in get_db_opponents(lvl)]; mo=next((o for o in opps_list if opp.lower() in o.lower()),None)
                    tc=len(get_db_tips(level=lvl,opponent=mo or "",status="active",internal=False)) if mo else 0
                    ha="vs" if g["home"] else "@"; sc="#2a7840" if "Final" in g["status"] else "#c87820" if "Progress" in g["status"] or "Live" in g["status"] else "#7a6a58"; tc_col="#c8341a" if tc>0 else "#9a8a78"
                    st.markdown(f'<div style="background:#e8dcc8;border:1px solid {color}44;border-top:3px solid {color};border-radius:8px;padding:12px 10px;text-align:center;min-height:150px;display:flex;flex-direction:column;justify-content:center;"><div style="font-family:monospace;font-size:10px;color:{color};font-weight:600;letter-spacing:.08em;margin-bottom:3px;">{lvl}</div><div style="font-size:11px;color:#7a6a58;font-family:monospace;line-height:1.3;margin-bottom:5px;">{al1}<br>{al2}</div><div style="font-size:12px;font-weight:600;color:#1a1410;line-height:1.3;margin-bottom:3px;">{ha} {ol1}<br>{ol2}</div><div style="font-size:10px;color:{sc};font-family:monospace;margin-bottom:4px;">{g["status"]}</div><div style="font-size:11px;color:{tc_col};font-weight:{"600" if tc>0 else "400"};">{tc} tip{"s" if tc!=1 else ""} on file</div></div>',unsafe_allow_html=True)
                    if mo and st.button("View tips" if tc>0 else "No tips yet",key=f"today_{lvl}",use_container_width=True,disabled=tc==0): go("opponent",level=lvl,opponent=mo)
                else:
                    st.markdown(f'<div style="background:#e8dcc8;border:1px solid #d8ccb8;border-top:3px solid {color};border-radius:8px;padding:12px 10px;text-align:center;min-height:150px;display:flex;flex-direction:column;justify-content:center;opacity:0.55;"><div style="font-family:monospace;font-size:10px;color:{color};font-weight:600;letter-spacing:.08em;margin-bottom:3px;">{lvl}</div><div style="font-size:11px;color:#7a6a58;font-family:monospace;line-height:1.3;margin-bottom:5px;">{al1}<br>{al2}</div><div style="font-size:13px;color:#9a8a78;margin-bottom:3px;">No game</div><div style="font-size:10px;color:#c8b898;font-family:monospace;">today</div></div>',unsafe_allow_html=True)
                    st.button("—",key=f"today_{lvl}",use_container_width=True,disabled=True)
        st.markdown("<br>",unsafe_allow_html=True)
        st.markdown('<div class="section-title">// SELECT A LEVEL</div>',unsafe_allow_html=True)
        ca,cb=st.columns(2)
        for i,(lvl,data) in enumerate(ORG.items()):
            lt=get_db_tips(level=lvl,status="active",internal=False); high=len([t for t in lt if t["confidence"]=="High"]); cl=sum(len(t["clips"]) for t in lt); color=LEVEL_COLORS[lvl]; opps=get_db_opponents(lvl)
            with (ca if i%2==0 else cb):
                st.markdown(f'<div class="level-card"><div class="level-card-header"><div><div class="level-card-title">{lvl} <span style="font-size:13px;color:{color};font-family:monospace;font-weight:400;">{data["affiliate"]}</span></div><div class="level-card-affiliate">{data["league"]} · {len(opps)} opponents</div></div><div class="level-card-count {"zero" if not lt else ""}">{len(lt)}</div></div><div class="level-divider"></div><div><span class="level-stat"><strong>{high}</strong> high conf</span><span class="level-stat"><strong>{cl}</strong> clips</span><span class="level-stat"><strong>{len(opps)}</strong> opponents</span></div></div>',unsafe_allow_html=True)
                if st.button(f"Open {lvl} →",key=f"home_{lvl}",use_container_width=True): go("level",level=lvl)
    with ht2:
        st.markdown('<div class="section-title">// TIPS ON OUR OWN PITCHERS — FLAGGED FOR REVIEW OR CORRECTION</div>',unsafe_allow_html=True)
        ic1,ic2,ic3=st.columns(3)
        ic1.markdown(f'<div class="stat-card"><div class="stat-card-value">{len(int_tips)}</div><div class="stat-card-label">Internal Tips</div></div>',unsafe_allow_html=True)
        ic2.markdown(f'<div class="stat-card"><div class="stat-card-value" style="color:#c8341a;">{len([t for t in int_tips if t["confidence"]=="High"])}</div><div class="stat-card-label">High Priority</div></div>',unsafe_allow_html=True)
        ic3.markdown(f'<div class="stat-card"><div class="stat-card-value">{len(set(t["name"] for t in int_tips))}</div><div class="stat-card-label">Players Flagged</div></div>',unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)
        af=st.selectbox("Filter by affiliate",["All Affiliates"]+list(OWN_AFFILIATES.values()),key="int_aff")
        it1,it2,it3=st.tabs(["Pitcher — Home Plate View","Pitcher — 2B View","Catcher Tips"])
        for tab,view in [(it1,"Pitcher — Home Plate View"),(it2,"Pitcher — 2B View"),(it3,"Catcher Tips")]:
            with tab:
                vt=get_db_tips(tip_view=view,internal=True,status="active")
                if af!="All Affiliates": vt=[t for t in vt if OWN_AFFILIATES.get(t["level"],"")==af]
                render_tips_in_view(vt,f"int_{view[:2]}")
        st.markdown("<br>",unsafe_allow_html=True)
        if st.button("+ Add Internal Tip",type="primary",key="add_int"): st.session_state.prefill_internal=True; go("add_tip")

# ── LEVEL ─────────────────────────────────────────────────────────────────────────
elif page=="level":
    lvl=st.session_state.selected_level
    if not lvl: go("home")
    data=ORG[lvl]; color=LEVEL_COLORS[lvl]
    st.markdown(f'<div class="breadcrumb">Home › <span class="current">{lvl} — {data["affiliate"]}</span></div>',unsafe_allow_html=True)
    if st.button("← Home"): go("home")
    st.markdown(f'<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:2px;">{lvl} <span style="color:{color};font-family:monospace;font-weight:400;">{data["affiliate"]}</span></div>',unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{data["league"]}</div>',unsafe_allow_html=True)
    srch=st.text_input("F",placeholder="Search opponents…",label_visibility="collapsed",key="opp_s")
    st.markdown('<div class="section-title">// OPPONENTS</div>',unsafe_allow_html=True)
    opps=[r["name"] for r in get_db_opponents(lvl)]
    if srch: opps=[o for o in opps if srch.lower() in o.lower()]
    for opp in opps:
        at=get_db_tips(level=lvl,opponent=opp,status="active",internal=False); pt=get_db_tips(level=lvl,opponent=opp,status="pending")
        high=len([t for t in at if t["confidence"]=="High"]); cl=sum(len(t["clips"]) for t in at)
        org_tag="("+opp.split("(")[1] if "(" in opp else ""
        st.markdown(f'<div class="opponent-card"><div><div class="opponent-name">{opp_short(opp)}</div><div class="opponent-meta">{org_tag}{"&nbsp;·&nbsp;⚠ pending" if pt else ""}</div></div><div style="text-align:right;"><div class="opp-count {"zero" if not at else ""}">{len(at)} tip{"s" if len(at)!=1 else ""}</div><div style="font-size:10px;color:#9a8a78;font-family:monospace;">{"{}h · {}c".format(high,cl) if at else "no tips yet"}</div></div></div>',unsafe_allow_html=True)
        if st.button(f"View {opp_short(opp)}",key=f"opp_{lvl}_{opp}",use_container_width=True): go("opponent",level=lvl,opponent=opp)

# ── OPPONENT ──────────────────────────────────────────────────────────────────────
elif page=="opponent":
    lvl=st.session_state.selected_level; opp=st.session_state.selected_opponent
    if not lvl or not opp: go("home")
    color=LEVEL_COLORS.get(lvl,"#5a4a38")
    st.markdown(f'<div class="breadcrumb">Home › {lvl} — {ORG[lvl]["affiliate"]} › <span class="current">{opp_short(opp)}</span></div>',unsafe_allow_html=True)
    if st.button(f"← Back to {lvl}"): go("level",level=lvl)
    at=get_db_tips(level=lvl,opponent=opp,status="active",internal=False); pt=get_db_tips(level=lvl,opponent=opp,status="pending")
    st.markdown(f'<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:2px;">{opp_short(opp)}</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{lvl} · {ORG[lvl]["league"]} · {len(at)} active tip{"s" if len(at)!=1 else ""}</div>',unsafe_allow_html=True)
    _,bc=st.columns([5,1])
    with bc:
        if st.button("+ Add Tip",type="primary",key="add_opp"): st.session_state.prefill_level=lvl; st.session_state.prefill_opponent=opp; st.session_state.prefill_internal=False; go("add_tip")
    if pt: st.markdown(f'<div style="font-size:12px;color:#c87820;font-family:monospace;margin-bottom:8px;">⚠ {len(pt)} pending</div>',unsafe_allow_html=True)
    if not at:
        st.markdown(f'<div class="empty-tab"><div style="font-size:14px;color:#9a8a78;">No active tips for {opp_short(opp)}</div></div>',unsafe_allow_html=True)
    else:
        ot1,ot2,ot3=st.tabs(["Pitcher — Home Plate View","Pitcher — 2B View","Catcher Tips"])
        for tab,view in [(ot1,"Pitcher — Home Plate View"),(ot2,"Pitcher — 2B View"),(ot3,"Catcher Tips")]:
            with tab: render_tips_in_view([t for t in at if t.get("tip_view","")==view],f"opp_{view[:2]}")

# ── TIP DETAIL ────────────────────────────────────────────────────────────────────
elif page=="tip_detail":
    tip=get_db_tip(st.session_state.selected_tip_id)
    if not tip: go("home")
    lvl=tip["level"]; opp=tip.get("opponent","")
    st.markdown(f'<div class="breadcrumb">Home › {lvl} › {opp_short(opp)} › <span class="current">{tip["name"]}</span></div>',unsafe_allow_html=True)
    cb,ce,cp=st.columns(3)
    with cb:
        if st.button("← Back"): go("opponent",level=lvl,opponent=opp)
    with ce:
        if st.button("Edit tip",key="edit_det"): st.session_state.editing_tip_id=tip["id"]; go("edit_tip")
    with cp:
        if st.button("Pitcher profile →",key="det_prof"): go("pitcher_profile",pitcher=tip["name"])
    jersey=f'#{tip["jersey_number"]}' if tip.get("jersey_number") and tip["jersey_number"] not in ("—","") else ""; pid=f'ID:{tip["mlb_player_id"]}' if tip.get("mlb_player_id") else ""
    st.markdown(f'<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:6px;">{jersey} {tip["name"]} <span style="font-size:12px;color:#9a8a78;font-family:monospace;">{pid}</span></div>',unsafe_allow_html=True)
    st.markdown(level_badge(tip["level"])+f'<span class="badge b-team">{tip["hand"]}</span>'+f'<span class="badge b-team">{opp_short(opp)}</span>'+view_badge(tip.get("tip_view",""))+status_badge(tip["status"])+conf_badge(tip["confidence"]),unsafe_allow_html=True)
    st.markdown("<br>",unsafe_allow_html=True)
    left,right=st.columns([1.4,1])
    with left:
        clips=tip.get("clips",[]); videos=[c for c in clips if c.get("clip_type","video")=="video"]; images=[c for c in clips if c.get("clip_type","video")=="image"]
        if videos:
            st.markdown('<div class="section-title">// VIDEO CLIPS</div>',unsafe_allow_html=True)
            ac=min(st.session_state.active_clip,len(videos)-1); clip=videos[ac]; src_color="#2a6090" if clip.get("source","")=="PitchBase" else "#5a4a90"
            st.markdown(f'<div class="video-box"><div style="font-family:monospace;font-size:10px;color:{src_color};margin-bottom:12px;">{clip.get("source","").upper()}</div><div style="font-size:44px;margin-bottom:10px;color:#3a2a1a;">▶</div><div style="font-size:13px;color:#a89878;margin-bottom:16px;">{clip.get("label","")}</div><a href="{clip.get("url","")}" target="_blank" style="color:#f0e8d8;font-size:12px;font-family:monospace;background:#c8341a;padding:7px 18px;border-radius:4px;text-decoration:none;">Open in {clip.get("source","")} ↗</a></div>',unsafe_allow_html=True)
            if len(videos)>1:
                cols=st.columns(min(len(videos),5))
                for i,c in enumerate(videos):
                    with cols[i]:
                        st.markdown(f'<div style="background:#e8dcc8;border:1px solid {"#c8341a" if i==ac else "#c8b898"};border-radius:5px;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;font-size:14px;color:#c8b898;">▶</div><div style="font-size:10px;color:#9a8a78;text-align:center;font-family:monospace;margin-top:3px;">{c.get("label","")[:14]}</div>',unsafe_allow_html=True)
                        if st.button(f"▶{i+1}",key=f"clip_{tip['id']}_{i}"): st.session_state.active_clip=i; st.rerun()
        if images:
            st.markdown('<div class="section-title">// IMAGES</div>',unsafe_allow_html=True)
            icols=st.columns(min(len(images),3))
            for i,img in enumerate(images):
                with icols[i%3]:
                    if img.get("data"): st.image(base64.b64decode(img["data"]),caption=img.get("label",""),use_container_width=True)
                    elif img.get("url"): st.image(img["url"],caption=img.get("label",""),use_container_width=True)
        if not videos and not images:
            st.markdown('<div class="video-box"><div style="font-size:13px;color:#a89878;">No media attached</div></div>',unsafe_allow_html=True)
        st.markdown('<div class="section-title" style="margin-top:16px;">// THE TELL</div>',unsafe_allow_html=True)
        vh=f'<div style="font-size:12px;color:#7a6a58;margin-top:8px;font-family:monospace;">Vantage: {tip["vantage"]}</div>' if tip.get("vantage") else ""
        st.markdown(f'<div class="detail-section"><div style="font-size:13px;color:#1a1410;line-height:1.7;">{tip["tell"]}</div>{vh}</div>',unsafe_allow_html=True)
        st.markdown('<div class="section-title" style="margin-top:16px;">// TIP HISTORY</div>',unsafe_allow_html=True)
        for h in sorted(tip.get("history",[]),key=lambda x:x["date"],reverse=True):
            st.markdown(f'<div class="history-entry"><div class="history-date">{h["date"]}</div><div style="font-size:13px;color:#1a1410;margin-top:2px;">{h["event"]}</div></div>',unsafe_allow_html=True)
    with right:
        cc={"High":"#2a7840","Medium":"#c87820","Low":"#c8341a"}.get(tip["confidence"],"#7a6a58")
        dots="".join([f'<span style="width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:3px;background:{cc if i<{"High":4,"Medium":2,"Low":1}.get(tip["confidence"],1) else "#d8ccb8"};"></span>' for i in range(5)])
        st.markdown(f'<div class="detail-section"><div class="detail-label">Confidence</div><div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">{dots}<span style="font-size:13px;font-weight:600;color:{cc};">{tip["confidence"]}</span></div><div style="font-size:12px;color:#7a6a58;">{tip["games"]} game{"s" if tip["games"]!=1 else ""} sampled</div></div>',unsafe_allow_html=True)
        st.markdown(f'<div class="detail-section"><div class="detail-label">Tip Info</div><div style="font-size:11px;color:#9a8a78;margin-bottom:2px;">View</div><div style="font-size:13px;color:#1a1410;margin-bottom:8px;">{tip.get("tip_view","—")}</div><div style="font-size:11px;color:#9a8a78;margin-bottom:2px;">Pitch tipped</div><div style="font-size:13px;color:#1a1410;margin-bottom:8px;">{tip["pitch"]}</div><div style="font-size:11px;color:#9a8a78;margin-bottom:2px;">Tell category</div><div style="font-size:13px;color:#1a1410;margin-bottom:8px;">{tip["tell_type"]}</div><div style="font-size:11px;color:#9a8a78;margin-bottom:2px;">Vantage</div><div style="font-size:13px;color:#1a1410;">{tip.get("vantage","—")}</div></div>',unsafe_allow_html=True)
        tags_html=" ".join([f'<span style="font-size:11px;padding:2px 7px;border-radius:99px;background:#d8ccb8;color:#7a6a58;border:1px solid #c8b898;">{t.strip()}</span>' for t in (tip.get("tags") or "").split(",") if t.strip()])
        st.markdown(f'<div class="detail-section"><div class="detail-label">Submission</div><div style="font-size:12px;color:#7a6a58;margin-bottom:8px;">By {tip["submitted_by_display"]} on {tip["date_added"]}</div>{tags_html}</div>',unsafe_allow_html=True)
        st.markdown('<div class="detail-label">Actions</div>',unsafe_allow_html=True)
        if tip["status"]=="pending":
            if st.button("Approve",type="primary",use_container_width=True,key="app_det"):
                hist=tip["history"]+[{"date":str(date.today()),"event":f"Approved by {user['display_name']}"}]
                update_db_tip(tip["id"],{"status":"active","history":hist}); st.success("Approved!"); st.rerun()
        if tip["status"]=="active":
            if st.button("Mark Inactive",use_container_width=True,key="inact_det"):
                hist=tip["history"]+[{"date":str(date.today()),"event":f"Marked inactive by {user['display_name']}"}]
                update_db_tip(tip["id"],{"status":"inactive","history":hist}); st.info("Marked inactive."); st.rerun()
        if is_admin():
            st.markdown("<hr>",unsafe_allow_html=True)
            st.markdown('<div style="font-size:11px;color:#9a8a78;font-family:monospace;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;">Delete Tip</div>',unsafe_allow_html=True)
            confirm_del = st.checkbox("Confirm permanent deletion", key="confirm_del")
            if confirm_del:
                if st.button("Delete Tip", use_container_width=True, key="del_tip"):
                    del_db_tip(tip["id"])
                    st.success("Tip deleted.")
                    go("home")

# ── EDIT TIP ──────────────────────────────────────────────────────────────────────
elif page=="edit_tip":
    tip=get_db_tip(st.session_state.editing_tip_id)
    if not tip: go("home")
    st.markdown(f'<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Edit Tip — {tip["name"]}</div>',unsafe_allow_html=True)
    if st.button("← Cancel"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
    lo=list(ORG.keys())
    with st.form("edit_form"):
        c1,c2=st.columns(2)
        name=c1.text_input("Pitcher Name",value=tip["name"]); hand=c2.selectbox("Throws",["RHP","LHP"],index=["RHP","LHP"].index(tip["hand"]))
        c3,c4=st.columns(2)
        level=c3.selectbox("Level",lo,index=lo.index(tip["level"]))
        opps_list=[r["name"] for r in get_db_opponents(level)]; oi=opps_list.index(tip["opponent"]) if tip["opponent"] in opps_list else 0
        opponent=c4.selectbox("Team",opps_list,index=oi)
        tv=st.selectbox("Tip View",TIP_VIEWS,index=TIP_VIEWS.index(tip["tip_view"]) if tip["tip_view"] in TIP_VIEWS else 0)
        c5,c6=st.columns(2)
        po=["Breaking ball","Fastball","Changeup","Curveball","Splitter","Cutter"]; tto=["Glove position","Arm slot","Timing / tempo","Grip / hand","Eye / head","Catcher setup","Footwork","Other"]
        pitch=c5.selectbox("Pitch Type",po,index=po.index(tip["pitch"]) if tip["pitch"] in po else 0)
        tell_type=c6.selectbox("Tell Category",tto,index=tto.index(tip["tell_type"]) if tip["tell_type"] in tto else 0)
        tell=st.text_area("Describe the Tell",value=tip["tell"],height=100)
        vantage=st.text_input("Best Vantage Point",value=tip.get("vantage",""))
        c7,c8=st.columns(2)
        co=["High","Medium","Low"]; confidence=c7.selectbox("Confidence",co,index=co.index(tip["confidence"]))
        games=c8.number_input("Games Sampled",min_value=1,value=tip["games"])
        tags=st.text_input("Tags",value=tip.get("tags",""))
        if st.form_submit_button("Save Changes",type="primary"):
            hist=tip["history"]+[{"date":str(date.today()),"event":f"Tip edited by {user['display_name']}"}]
            update_db_tip(tip["id"],{"name":name,"hand":hand,"opponent":opponent,"level":level,"tip_view":tv,"pitch":pitch,"tell_type":tell_type,"tell":tell,"vantage":vantage,"confidence":confidence,"games":int(games),"tags":tags,"history":hist})
            st.success("Tip updated."); go("tip_detail",level=level,opponent=opponent,tip_id=tip["id"])

# ── ADD TIP ───────────────────────────────────────────────────────────────────────
elif page=="add_tip":
    is_internal=st.session_state.get("prefill_internal",False)
    st.markdown(f'<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Submit a {"Internal " if is_internal else ""}Tip</div>',unsafe_allow_html=True)
    if st.button("← Back"): st.session_state.selected_player=None; go("home" if is_internal else "all_tips")

    st.markdown('<div class="section-title">// FIND PITCHER</div>',unsafe_allow_html=True)
    sq=st.text_input("Search by pitcher name",placeholder="Type 3+ characters…",key="player_search_q")
    if sq and len(sq)>=3:
        with st.spinner("Searching…"):
            results=search_mlb_players(sq)
        if not results:
            st.markdown('<div style="font-size:13px;color:#9a8a78;padding:8px 0;">No pitchers found. Try a different spelling.</div>',unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="font-size:11px;color:#9a8a78;font-family:monospace;margin-bottom:8px;">{len(results)} result{"s" if len(results)!=1 else ""} — select a pitcher:</div>',unsafe_allow_html=True)
            for p in results[:10]:
                ci,cb2=st.columns([5,1])
                with ci: st.markdown(f'<div class="player-result"><div style="display:flex;align-items:center;gap:10px;"><span style="font-size:16px;font-weight:600;color:#9a8a78;font-family:monospace;">#{p["jersey"]}</span><span style="font-size:14px;font-weight:600;color:#1a1410;">{p["name"]}</span><span class="badge b-team">{p["hand"]}</span>{level_badge(p["level"])}<span style="font-size:12px;color:#7a6a58;">{p["team"]}</span><span style="font-size:10px;color:#9a8a78;font-family:monospace;">ID:{p["id"]}</span></div></div>',unsafe_allow_html=True)
                with cb2:
                    if st.button("Select",key=f"sel_{p['id']}"): st.session_state.selected_player=p; st.rerun()

    selected=st.session_state.get("selected_player")
    if selected:
        st.markdown(f'<div class="player-selected"><div style="display:flex;align-items:center;gap:12px;"><div style="font-size:20px;font-weight:600;color:#9a8a78;font-family:monospace;">#{selected["jersey"]}</div><div><div style="font-size:15px;font-weight:600;color:#1a1410;">{selected["name"]}</div><div style="font-size:12px;color:#7a6a58;font-family:monospace;">{selected["hand"]} · {selected["team"]} · {selected["level"]} · MLB ID:{selected["id"]}</div></div><div style="margin-left:auto;"><span style="font-size:11px;color:#c8341a;font-family:monospace;font-weight:600;">SELECTED</span></div></div></div>',unsafe_allow_html=True)
        if st.button("Clear selection",key="clear_player"): st.session_state.selected_player=None; st.rerun()

    if is_admin():
        with st.expander("Admin Override — manually enter player info"):
            ov1,ov2,ov3=st.columns(3)
            ovn=ov1.text_input("Player Name",key="ov_name"); ovj=ov2.text_input("Jersey #",key="ov_jersey"); ovh=ov3.selectbox("Throws",["RHP","LHP"],key="ov_hand")
            ov4,ov5=st.columns(2); ovl=ov4.selectbox("Level",LEVEL_ORDER,key="ov_level"); ovt=ov5.text_input("Team",key="ov_team")
            if st.button("Use Manual Entry",key="use_override") and ovn.strip():
                st.session_state.selected_player={"id":None,"name":ovn.strip(),"jersey":ovj.strip() or "—","hand":ovh,"team":ovt.strip(),"level":ovl,"team_id":None}; st.rerun()

    st.markdown("---")
    if not selected:
        st.markdown('<div style="font-size:13px;color:#9a8a78;text-align:center;padding:20px;">Search for and select a pitcher above to continue.</div>',unsafe_allow_html=True)
    else:
        auto_level=selected.get("level","AAA"); auto_team=selected.get("team","")
        lo=list(ORG.keys())

        # Resolve team — searches across all levels if API returns unknown level
        matched_opp, resolved_level = find_opp_match(auto_team, auto_level)
        # If match found at a different level, use that level
        if matched_opp and resolved_level != auto_level:
            auto_level = resolved_level
        final_opponent = None; final_level = auto_level

        st.markdown(f'<div class="section-title">// TIP DETAILS FOR #{selected["jersey"]} {selected["name"]}</div>',unsafe_allow_html=True)
        lc1,lc2=st.columns(2)
        with lc1:
            if is_admin(): final_level=st.selectbox("Level",lo,index=lo.index(auto_level) if auto_level in lo else 1)
            else: st.markdown(f'<div class="locked-label">Level</div><div class="locked-field">{auto_level}</div>',unsafe_allow_html=True)
        with lc2:
            if is_internal:
                to=list(OWN_AFFILIATES.values()); dt=OWN_AFFILIATES.get(final_level,to[0])
                final_opponent=st.selectbox("Our Affiliate",to,index=to.index(dt) if dt in to else 0)
            elif matched_opp:
                if is_admin():
                    all_opps=[r["name"] for r in get_db_opponents(final_level)]; oi=all_opps.index(matched_opp) if matched_opp in all_opps else 0
                    final_opponent=st.selectbox("Team",all_opps,index=oi)
                else:
                    st.markdown(f'<div class="locked-label">Team</div><div class="locked-field">{matched_opp}</div>',unsafe_allow_html=True)
                    final_opponent=matched_opp
            else:
                st.warning(f"**{auto_team}** is not in our opponent list for {auto_level}.")
                if st.button(f"Request to add {auto_team}",type="primary",key="req_team"):
                    add_team_request(auto_level,auto_team,user["username"],user["display_name"],selected.get("id"),selected["name"])
                    st.success(f"Request sent to admin to add {auto_team} to {auto_level}.")

        if not is_internal and not matched_opp and not is_admin():
            st.info("Submit a team request above. Tip submission is paused until the team is approved.")
        else:
            # Media section OUTSIDE form so radio toggles work live
            st.markdown("---")
            st.markdown("**Media** — add video clips and/or still images")
            media_entries=[]
            for idx,row in enumerate(st.session_state.media_rows):
                st.markdown(f'<div class="media-slot">',unsafe_allow_html=True)
                mc1,mc2=st.columns([2,5])
                mtype=mc1.radio("Type",["Video","Image"],horizontal=True,key=f"mtype_{idx}")
                if mtype=="Video":
                    mc3,mc4=mc2.columns([2,4])
                    src=mc3.selectbox("Source",["PitchBase","TruMedia","Other"],key=f"msrc_{idx}")
                    url=mc4.text_input("URL",placeholder="https://…",key=f"murl_{idx}")
                    lbl=mc2.text_input("Label",placeholder="e.g. BB — tell present",key=f"mlbl_{idx}",label_visibility="collapsed")
                    media_entries.append({"clip_type":"video","source":src,"url":url,"label":lbl,"data":None})
                else:
                    uploaded=mc2.file_uploader("Drag & drop or click to upload image",type=["jpg","jpeg","png","gif"],key=f"mfile_{idx}")
                    lbl=mc2.text_input("Label",placeholder="e.g. Glove position — tell present",key=f"mimlbl_{idx}",label_visibility="collapsed")
                    img_data=base64.b64encode(uploaded.read()).decode() if uploaded else None
                    media_entries.append({"clip_type":"image","source":"upload","url":"","label":lbl,"data":img_data})
                st.markdown('</div>',unsafe_allow_html=True)
            if st.button("+ Add Media",key="add_media_btn"): st.session_state.media_rows.append({"type":"video"}); st.rerun()
            st.markdown("---")

            with st.form("atf"):
                tv=st.selectbox("Tip View *",TIP_VIEWS)
                c5,c6=st.columns(2)
                pitch=c5.selectbox("Pitch Type",["Breaking ball","Fastball","Changeup","Curveball","Splitter","Cutter"])
                tell_type=c6.selectbox("Tell Category",["Glove position","Arm slot","Timing / tempo","Grip / hand","Eye / head","Catcher setup","Footwork","Other"])
                tell=st.text_area("Describe the Tell *",placeholder="Be specific enough that a hitter can act on it.",height=100)
                vantage=st.text_input("Best Vantage Point",placeholder="e.g. 1B dugout, CF camera")
                c7,c8=st.columns(2)
                confidence=c7.selectbox("Confidence",["High","Medium","Low"],index=1)
                games=c8.number_input("Games Sampled",min_value=1,value=1)
                tags=st.text_input("Tags",placeholder="e.g. video confirmed, men on base")
                submitted=st.form_submit_button("Submit for Review",type="primary")
                if submitted:
                    if not tell.strip(): st.error("Tell description is required.")
                    elif not final_opponent: st.error("Team must be resolved first.")
                    else:
                        clips=[m for m in media_entries if m.get("url","").strip() or m.get("data")]
                        add_db_tip({"mlb_player_id":selected.get("id"),"name":selected["name"],"jersey_number":selected["jersey"],"hand":selected["hand"],"opponent":final_opponent,"level":final_level,"tip_view":tv,"internal":is_internal,"pitch":pitch,"tell_type":tell_type,"tell":tell.strip(),"vantage":vantage,"confidence":confidence,"games":int(games),"tags":tags,"clips":clips,"status":"pending","submitted_by":user["username"],"submitted_by_display":user["display_name"],"date_added":str(date.today()),"history":[{"date":str(date.today()),"event":f"Tip submitted by {user['display_name']} (MLB ID:{selected.get('id','manual')})"}]})
                        st.session_state.selected_player=None; st.session_state.media_rows=[{"type":"video"}]
                        st.session_state.prefill_level=None; st.session_state.prefill_opponent=None; st.session_state.prefill_internal=False
                        st.session_state["tip_submitted_name"] = selected["name"]
                        go("tip_submitted")

# ── PITCHER PROFILE ────────────────────────────────────────────────────────────────
elif page=="pitcher_profile":
    name=st.session_state.selected_pitcher
    if not name: go("home")
    all_p=get_db_tips(name=name); active_p=[t for t in all_p if t["status"]=="active"]; inactive_p=[t for t in all_p if t["status"]=="inactive"]; pending_p=[t for t in all_p if t["status"]=="pending"]
    latest=sorted(all_p,key=lambda x:x["date_added"],reverse=True)
    cl=latest[0]["level"] if latest else "—"; co=latest[0].get("opponent","—") if latest else "—"; hand=latest[0]["hand"] if latest else "—"
    jersey=f'#{latest[0]["jersey_number"]}' if latest and latest[0].get("jersey_number") and latest[0]["jersey_number"] not in ("—","") else ""
    pid=f'ID:{latest[0]["mlb_player_id"]}' if latest and latest[0].get("mlb_player_id") else ""
    if st.button("← Back"): st.session_state.page="home"; st.rerun()
    st.markdown(f'<div style="background:#e8dcc8;border:1px solid #c8b898;border-radius:10px;padding:20px 24px;margin-bottom:20px;"><div style="display:flex;align-items:flex-start;justify-content:space-between;"><div><div style="font-size:24px;font-weight:600;color:#1a1410;margin-bottom:6px;">{jersey} {name} <span style="font-size:13px;color:#9a8a78;font-family:monospace;">{pid}</span></div><div>{level_badge(cl)}<span class="badge b-team">{hand}</span><span class="badge b-team">{opp_short(co)}</span></div></div><div style="text-align:right;"><div style="font-size:22px;font-weight:600;color:#c8341a;font-family:monospace;">{len(active_p)}</div><div style="font-size:10px;color:#9a8a78;font-family:monospace;text-transform:uppercase;letter-spacing:.1em;">active tips</div></div></div></div>',unsafe_allow_html=True)
    with st.expander("Promote / Demote Pitcher"):
        pc1,pc2,pc3=st.columns([2,3,1])
        nl=pc1.selectbox("New Level",LEVEL_ORDER,key="promo_level"); no=pc2.selectbox("New Team",[r["name"] for r in get_db_opponents(nl)],key="promo_opp")
        with pc3:
            st.markdown("<br>",unsafe_allow_html=True)
            if st.button("Move",type="primary",key="do_promo"):
                today=str(date.today())
                for t in active_p:
                    hist=t["history"]+[{"date":today,"event":f"Moved from {t['level']} ({opp_short(t.get('opponent',''))}) to {nl} ({opp_short(no)}) by {user['display_name']}"}]
                    update_db_tip(t["id"],{"level":nl,"opponent":no,"history":hist})
                st.success(f"{name} moved to {nl}."); st.rerun()
    st.markdown('<div class="section-title">// ACTIVE TIPS</div>',unsafe_allow_html=True)
    if not active_p and not pending_p: st.info("No active tips on file.")
    else:
        for tip in sorted(active_p+pending_p,key=lambda x:x["date_added"],reverse=True):
            render_pitcher_card(tip)
            pc1,pc2=st.columns(2)
            with pc1:
                if st.button("View →",key=f"pp_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
            with pc2:
                if st.button("Edit",key=f"pped_{tip['id']}"): st.session_state.editing_tip_id=tip["id"]; go("edit_tip")
    st.markdown("<br>",unsafe_allow_html=True)
    if inactive_p:
        if st.button(f"{'Hide' if st.session_state.show_inactive_tips else 'View'} Inactive Tips ({len(inactive_p)})",key="tog_inactive"):
            st.session_state.show_inactive_tips=not st.session_state.show_inactive_tips; st.rerun()
        if st.session_state.show_inactive_tips:
            st.markdown('<div class="section-title">// INACTIVE TIPS</div>',unsafe_allow_html=True)
            for tip in sorted(inactive_p,key=lambda x:x["date_added"],reverse=True):
                render_pitcher_card(tip)
                if st.button("View →",key=f"ppi_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
    st.markdown("<br>",unsafe_allow_html=True)
    st.markdown('<div class="section-title">// TIP HISTORY LOG</div>',unsafe_allow_html=True)
    evts=sorted([{**h,"tip_pitch":t["pitch"],"tip_level":t["level"]} for t in all_p for h in t.get("history",[])],key=lambda x:x["date"],reverse=True)
    if evts:
        for ev in evts: st.markdown(f'<div class="history-entry"><div class="history-date">{ev["date"]} · {ev["tip_level"]} · {ev["tip_pitch"]}</div><div style="font-size:13px;color:#1a1410;margin-top:2px;">{ev["event"]}</div></div>',unsafe_allow_html=True)
    else: st.markdown('<div style="font-size:12px;color:#9a8a78;">No history entries yet.</div>',unsafe_allow_html=True)

# ── TIP SUBMITTED ────────────────────────────────────────────────────────────────
elif page=="tip_submitted":
    pitcher_name = st.session_state.get("tip_submitted_name", "the pitcher")
    st.markdown(f"""
    <div style="max-width:500px;margin:80px auto;text-align:center;">
        <div style="width:64px;height:64px;border-radius:50%;background:#0a3a1822;border:2px solid #2a7840;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;font-size:28px;">✓</div>
        <div style="font-size:24px;font-weight:600;color:#1a1410;margin-bottom:8px;">Tip Submitted</div>
        <div style="font-size:14px;color:#7a6a58;font-family:monospace;margin-bottom:6px;">{pitcher_name}</div>
        <div style="font-size:13px;color:#9a8a78;margin-bottom:32px;">Your tip is pending review by an admin.<br>You'll be able to see it under My Account once approved.</div>
        <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;"></div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Submit Another Tip", type="primary", use_container_width=True):
            go("add_tip")
    with c2:
        if st.button("Go to Home", use_container_width=True):
            go("home")

# ── QUEUE ─────────────────────────────────────────────────────────────────────────
elif page=="queue":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Pending Review</div>',unsafe_allow_html=True)
    pend=get_db_tips(status="pending")
    if not pend: st.success("All caught up — no pending tips.")
    else:
        for tip in pend:
            il=" [INTERNAL]" if tip.get("internal") else ""
            st.markdown(f'<div class="queue-card"><div class="queue-header"><span class="queue-title">{tip["name"]} — {opp_short(tip.get("opponent",""))} ({tip["level"]}){il}</span><span style="font-size:11px;color:#7a6a58;margin-left:8px;">by {tip["submitted_by_display"]} · {tip["date_added"]} · {tip.get("tip_view","")}</span></div><div class="queue-body"><div style="font-size:13px;color:#1a1410;margin-bottom:4px;"><strong>{tip["tell_type"]}:</strong> {tip["tell"][:150]}{"..." if len(tip["tell"])>150 else ""}</div><div style="font-size:11px;color:#9a8a78;font-family:monospace;">{len(tip["clips"])} media · {tip["confidence"]} · {tip["games"]} game(s)</div></div></div>',unsafe_allow_html=True)
            q1,q2,q3=st.columns([1,1,2])
            with q1:
                if st.button("Approve",key=f"qa_{tip['id']}",type="primary"):
                    hist=tip["history"]+[{"date":str(date.today()),"event":f"Approved by {user['display_name']}"}]
                    update_db_tip(tip["id"],{"status":"active","history":hist}); st.rerun()
            with q2:
                if st.button("Reject",key=f"qr_{tip['id']}"):
                    hist=tip["history"]+[{"date":str(date.today()),"event":f"Rejected by {user['display_name']}"}]
                    update_db_tip(tip["id"],{"status":"inactive","history":hist}); st.rerun()
            with q3:
                if st.button("View →",key=f"qv_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])

# ── TEAM REQUESTS ─────────────────────────────────────────────────────────────────
elif page=="team_requests":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Team Requests</div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">// SCOUTS REQUESTING NEW TEAMS BE ADDED TO OPPONENT LISTS</div>',unsafe_allow_html=True)
    if not is_admin(): st.warning("Admin access required."); st.stop()
    reqs=get_team_requests(status="pending")
    if not reqs: st.success("No pending team requests.")
    else:
        for req in reqs:
            player_line = f'<div style="font-size:12px;color:#9a8a78;font-family:monospace;margin-top:4px;">For player: {req["player_name"]} (ID:{req["mlb_player_id"]})</div>' if req.get("player_name") else ""
            st.markdown(f'<div class="team-request-card"><div style="font-size:14px;font-weight:600;color:#1a1410;margin-bottom:4px;">{req["team_name"]} <span style="font-size:12px;color:#9a8a78;">→ {req["level"]}</span></div><div style="font-size:12px;color:#7a6a58;">Requested by {req["requested_by_display"]} on {req["date_requested"]}</div>{player_line}</div>',unsafe_allow_html=True)
            r1,r2=st.columns(2)
            with r1:
                if st.button("Approve — Add Team",key=f"tr_app_{req['id']}",type="primary"):
                    resolve_team_request(req["id"],True,req["level"],req["team_name"]); st.success(f"Added {req['team_name']} to {req['level']}."); st.rerun()
            with r2:
                if st.button("Reject",key=f"tr_rej_{req['id']}"):
                    resolve_team_request(req["id"],False,req["level"],req["team_name"]); st.info("Request rejected."); st.rerun()

# ── SERIES PREP ───────────────────────────────────────────────────────────────────
elif page=="series_prep":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Series Prep</div>',unsafe_allow_html=True)
    c1,c2=st.columns(2)
    sl=c1.selectbox("Level",LEVEL_ORDER,key="sp_level"); so=c2.selectbox("Team",[r["name"] for r in get_db_opponents(sl)],key="sp_opp")
    avail=get_db_tips(level=sl,opponent=so,status="active",internal=False)
    st.markdown("<br>",unsafe_allow_html=True)
    if not avail:
        st.markdown(f'<div class="empty-tab"><div style="font-size:14px;color:#7a6a58;">No active tips on file for {opp_short(so)} at {sl}</div></div>',unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="section-title">// SELECT TIPS TO INCLUDE — {len(avail)} available</div>',unsafe_allow_html=True)
        sids=[]
        for view in TIP_VIEWS:
            vt=[t for t in avail if t.get("tip_view","")==view]
            if not vt: continue
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:#c8341a;font-family:monospace;text-transform:uppercase;margin:12px 0 6px;">{view}</div>',unsafe_allow_html=True)
            for tip in sorted(vt,key=lambda x:{"High":0,"Medium":1,"Low":2}.get(x["confidence"],3)):
                cc={"High":"#2a7840","Medium":"#c87820","Low":"#c8341a"}.get(tip["confidence"],"#7a6a58")
                cc1,ci=st.columns([1,8])
                with cc1: checked=st.checkbox("",key=f"sp_{tip['id']}",value=True)
                with ci: st.markdown(f'<div style="background:#e8dcc8;border:1px solid #c8b898;border-radius:6px;padding:10px 14px;"><div style="display:flex;align-items:center;gap:8px;"><span style="font-size:14px;font-weight:600;color:#1a1410;">{tip["name"]}</span><span class="badge b-team">{tip["hand"]}</span><span style="font-size:12px;font-weight:600;color:{cc};">{tip["confidence"]}</span><span style="font-size:12px;color:#7a6a58;">{tip["pitch"]} · {tip["tell_type"]}</span></div><div style="font-size:12px;color:#5a4a38;margin-top:4px;">{tip["tell"][:100]}{"..." if len(tip["tell"])>100 else ""}</div></div>',unsafe_allow_html=True)
                if checked: sids.append(tip["id"])
        st.markdown("<br>",unsafe_allow_html=True)
        stips=[t for t in avail if t["id"] in sids]
        if stips:
            if st.button("Generate PDF Report",type="primary"):
                pb=generate_series_pdf(sl,so,stips,str(date.today()))
                if pb: st.download_button("Download PDF",data=pb,file_name=f"SnakeEyes_{opp_short(so).replace(' ','_')}_{date.today()}.pdf",mime="application/pdf",type="primary")
                else: st.error("PDF failed. Run: pip3 install reportlab")
        else: st.info("Select at least one tip.")

# ── SEARCH ────────────────────────────────────────────────────────────────────────
elif page=="search":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Search</div>',unsafe_allow_html=True)
    query=st.text_input("Search",placeholder="Pitcher name, tell type, opponent, pitch…",key="sq")
    if query and len(query)>=2:
        conn,db=get_db(); q=f"%{query.lower()}%"
        results=fetchall(conn,db,"SELECT * FROM tips WHERE LOWER(name) LIKE %s OR LOWER(tell) LIKE %s OR LOWER(opponent) LIKE %s OR LOWER(tell_type) LIKE %s OR LOWER(pitch) LIKE %s OR LOWER(tags) LIKE %s ORDER BY date_added DESC",(q,q,q,q,q,q)); conn.close()
        for d in results:
            d["clips"]=json.loads(d["clips"] or "[]"); d["history"]=json.loads(d["history"] or "[]"); d["internal"]=bool(d["internal"])
        if not results: st.info("No results found.")
        else:
            st.markdown(f'<div class="section-title">// {len(results)} result{"s" if len(results)!=1 else ""}</div>',unsafe_allow_html=True)
            for tip in results:
                st.markdown(f'<div class="search-result"><div style="font-size:14px;font-weight:600;color:#1a1410;">{tip["name"]} <span style="font-size:12px;color:#7a6a58;font-weight:400;">· {opp_short(tip.get("opponent",""))} · {tip["level"]}</span></div><div style="font-size:12px;color:#5a4a38;margin-top:2px;"><strong>{tip["tell_type"]}:</strong> {tip["tell"][:100]}{"..." if len(tip["tell"])>100 else ""}</div><div style="font-size:11px;color:#9a8a78;font-family:monospace;margin-top:2px;">{tip["pitch"]} · {tip.get("tip_view","—")} · {tip["confidence"]} · {tip["status"]} · {tip["date_added"]}</div></div>',unsafe_allow_html=True)
                sc1,sc2=st.columns(2)
                with sc1:
                    if st.button("View tip →",key=f"sr_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
                with sc2:
                    if st.button("Pitcher →",key=f"srp_{tip['id']}"): go("pitcher_profile",pitcher=tip["name"])
    elif query: st.caption("Keep typing…")
    else: st.markdown('<div class="empty-tab"><div style="font-size:14px;color:#7a6a58;">Search by pitcher name, tell type, opponent, pitch type, or tags</div></div>',unsafe_allow_html=True)

# ── ALL TIPS ──────────────────────────────────────────────────────────────────────
elif page=="all_tips":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">All Tips</div>',unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6=st.columns([3,2,2,2,2,2])
    srch=c1.text_input("S",placeholder="Pitcher, tell, opponent…",label_visibility="collapsed")
    fl=c2.selectbox("L",["All Levels"]+list(ORG.keys()),label_visibility="collapsed")
    fv=c3.selectbox("V",["All Views"]+TIP_VIEWS,label_visibility="collapsed")
    fc=c4.selectbox("C",["All Confidence","High","Medium","Low"],label_visibility="collapsed")
    fp=c5.selectbox("P",["All Pitches","Breaking ball","Fastball","Changeup","Curveball","Splitter","Cutter"],label_visibility="collapsed")
    fs=c6.selectbox("St",["Active Only","All","Pending Only","Inactive"],label_visibility="collapsed")
    conn,db=get_db(); q="SELECT * FROM tips WHERE 1=1"; params=[]
    if fs=="Active Only":   q+=" AND status='active'"
    if fs=="Pending Only":  q+=" AND status='pending'"
    if fs=="Inactive":      q+=" AND status='inactive'"
    if fl!="All Levels":    q+=" AND level=%s"; params.append(fl)
    if fv!="All Views":     q+=" AND tip_view=%s"; params.append(fv)
    if fc!="All Confidence":q+=" AND confidence=%s"; params.append(fc)
    if fp!="All Pitches":   q+=" AND pitch=%s"; params.append(fp)
    if srch: s=f"%{srch.lower()}%"; q+=" AND (LOWER(name) LIKE %s OR LOWER(tell) LIKE %s OR LOWER(opponent) LIKE %s)"; params+=[s,s,s]
    q+=" ORDER BY date_added DESC"
    tips=fetchall(conn,db,q,params); conn.close()
    for d in tips:
        d["clips"]=json.loads(d["clips"] or "[]"); d["history"]=json.loads(d["history"] or "[]"); d["internal"]=bool(d["internal"])
    if not tips: st.info("No tips match your filters.")
    else:
        for tip in tips:
            render_pitcher_card(tip)
            at1,at2,at3=st.columns(3)
            with at1:
                if st.button("View →",key=f"av_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
            with at2:
                if st.button("Edit",key=f"aved_{tip['id']}"): st.session_state.editing_tip_id=tip["id"]; go("edit_tip")
            with at3:
                if st.button("Pitcher →",key=f"avp_{tip['id']}"): go("pitcher_profile",pitcher=tip["name"])
    st.markdown("---")
    if st.button("+ Add New Tip",type="primary"): go("add_tip")

# ── ACCOUNT ───────────────────────────────────────────────────────────────────────
elif page=="account":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">My Account</div>',unsafe_allow_html=True)
    st.markdown(f'<div style="background:#e8dcc8;border:1px solid #c8b898;border-radius:10px;padding:20px 24px;margin-bottom:20px;"><div style="display:flex;align-items:center;gap:16px;"><div style="width:52px;height:52px;border-radius:50%;background:#c8341a22;border:1px solid #c8341a44;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:600;color:#c8341a;flex-shrink:0;">{user["display_name"][:2].upper()}</div><div><div style="font-size:20px;font-weight:600;color:#1a1410;">{user["display_name"]}</div><div style="font-size:12px;color:#9a8a78;font-family:monospace;margin-top:2px;">@{user["username"]} · {user["role"]} · Default: {user["default_level"]}</div></div></div></div>',unsafe_allow_html=True)
    at1,at2=st.tabs(["My Submitted Tips","Change Password"])
    with at1:
        sf=st.selectbox("Filter by status",["All","Active","Pending","Inactive"],key="acc_status")
        conn,db=get_db(); q="SELECT * FROM tips WHERE submitted_by=%s"; params=[user["username"]]
        if sf=="Active":   q+=" AND status='active'"
        if sf=="Pending":  q+=" AND status='pending'"
        if sf=="Inactive": q+=" AND status='inactive'"
        q+=" ORDER BY date_added DESC"
        mt=fetchall(conn,db,q,params); conn.close()
        for d in mt:
            d["clips"]=json.loads(d["clips"] or "[]"); d["history"]=json.loads(d["history"] or "[]"); d["internal"]=bool(d["internal"])
        if not mt: st.markdown('<div class="empty-tab"><div style="font-size:14px;color:#7a6a58;">No tips submitted yet</div></div>',unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="font-size:12px;color:#7a6a58;font-family:monospace;margin-bottom:12px;">{len(mt)} tip{"s" if len(mt)!=1 else ""} found</div>',unsafe_allow_html=True)
            for tip in mt:
                render_pitcher_card(tip)
                ac1,ac2,ac3=st.columns(3)
                with ac1:
                    if st.button("View →",key=f"acc_view_{tip['id']}"): go("tip_detail",level=tip["level"],opponent=tip.get("opponent"),tip_id=tip["id"])
                with ac2:
                    if st.button("Edit",key=f"acc_edit_{tip['id']}"): st.session_state.editing_tip_id=tip["id"]; go("edit_tip")
                with ac3:
                    if st.button("Pitcher →",key=f"acc_pit_{tip['id']}"): go("pitcher_profile",pitcher=tip["name"])
    with at2:
        with st.form("change_pw"):
            cp_=st.text_input("Current Password",type="password"); np_=st.text_input("New Password",type="password"); cp2=st.text_input("Confirm New Password",type="password")
            if st.form_submit_button("Update Password",type="primary"):
                if not cp_ or not np_ or not cp2: st.error("All fields required.")
                elif np_!=cp2: st.error("New passwords do not match.")
                elif len(np_)<6: st.error("Password must be at least 6 characters.")
                elif not check_db_login(user["username"],cp_): st.error("Current password is incorrect.")
                else: update_db_password(user["id"],np_); st.success("Password updated.")

# ── VIDEO ─────────────────────────────────────────────────────────────────────────
elif page=="video":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Video Sources</div>',unsafe_allow_html=True)
    vc1,vc2=st.columns(2)
    for col,svc,color in [(vc1,"PitchBase","#2a6090"),(vc2,"TruMedia","#5a4a90")]:
        with col:
            cs=st.session_state.video_connections[svc]; sc="#2a7840" if cs else "#9a8a78"
            st.markdown(f'<div class="connect-card"><div style="font-family:monospace;font-size:16px;font-weight:600;color:{color};margin-bottom:6px;">{svc}</div><div style="font-size:12px;color:#5a4a38;line-height:1.6;margin-bottom:14px;">Link your {svc} account to attach clips directly when creating tips.</div><div style="display:flex;align-items:center;gap:6px;"><span style="width:7px;height:7px;border-radius:50%;background:{sc};display:inline-block;"></span><span style="font-size:11px;color:{sc};font-family:monospace;">{"Connected" if cs else "Not connected"}</span></div></div>',unsafe_allow_html=True)
            if st.button(f'{"Disconnect" if cs else "Connect"} {svc}',key=f"vc_{svc}",use_container_width=True): st.session_state.video_connections[svc]=not cs; st.rerun()

# ── ADMIN ─────────────────────────────────────────────────────────────────────────
elif page=="admin":
    st.markdown('<div style="font-size:20px;font-weight:600;color:#1a1410;margin-bottom:4px;">Admin</div>',unsafe_allow_html=True)
    if not is_admin(): st.warning("Admin access required."); st.stop()
    tab1,tab2,tab3=st.tabs(["Users","Add User","Manage Opponents"])
    with tab1:
        for u in get_db_users():
            with st.expander(f"{u['display_name']} · @{u['username']} · {u['role']}"):
                with st.form(f"eu_{u['id']}"):
                    uc1,uc2=st.columns(2)
                    nd=uc1.text_input("Display Name",value=u["display_name"],key=f"uname_{u['id']}")
                    nr=uc2.selectbox("Role",["Scout","Analyst","Coach","Admin"],index=["Scout","Analyst","Coach","Admin"].index(u["role"]) if u["role"] in ["Scout","Analyst","Coach","Admin"] else 0,key=f"urole_{u['id']}")
                    nl=st.selectbox("Default Level",LEVEL_ORDER,index=LEVEL_ORDER.index(u["default_level"]) if u["default_level"] in LEVEL_ORDER else 0,key=f"ulvl_{u['id']}")
                    st.markdown(f'<div style="font-size:11px;color:#9a8a78;font-family:monospace;">Username: {u["username"]} · Added: {u["created_at"]}</div>',unsafe_allow_html=True)
                    ucs,ucd=st.columns([3,1])
                    with ucs:
                        if st.form_submit_button("Save Changes",type="primary"):
                            if not nd.strip(): st.error("Name cannot be empty.")
                            else:
                                update_db_user(u["id"],nd,nr,nl)
                                if u["id"]==user["id"]: st.session_state.user["display_name"]=nd.strip(); st.session_state.user["role"]=nr; st.session_state.user["default_level"]=nl
                                st.success(f"Updated {nd}."); st.rerun()
                    with ucd:
                        if st.form_submit_button("Remove"):
                            if u["id"]==user["id"]: st.error("Cannot remove your own account.")
                            else: del_db_user(u["id"]); st.success("Removed."); st.rerun()
    with tab2:
        with st.form("new_user"):
            nu1,nu2=st.columns(2); nd=nu1.text_input("Full Name"); nu=nu2.text_input("Username")
            nu3,nu4=st.columns(2); npw=nu3.text_input("Password",type="password"); nr=nu4.selectbox("Role",["Scout","Analyst","Coach","Admin"])
            nl=st.selectbox("Default Level",LEVEL_ORDER)
            if st.form_submit_button("Create User",type="primary"):
                if not nd or not nu or not npw: st.error("All fields required.")
                else:
                    ok,msg=add_db_user(nu,nd,npw,nr,nl)
                    if ok: st.success(f"User '{nd}' created. Login: '{nu.lower()}'")
                    else: st.error(msg)
    with tab3:
        el=st.selectbox("Level to edit",list(ORG.keys()),key="adm_lvl")
        opps=[r["name"] for r in get_db_opponents(el)]
        st.markdown(f'**{el} — {ORG[el]["affiliate"]} — {len(opps)} opponents**')
        for o in opps:
            oa,ob=st.columns([5,1]); oa.markdown(f'<div style="padding:6px 0;font-size:13px;color:#5a4a38;">{o}</div>',unsafe_allow_html=True)
            if ob.button("Remove",key=f"del_{el}_{o}"): del_db_opponent(el,o); st.rerun()
        st.markdown("---")
        on,oa2=st.columns([4,1]); no=on.text_input("New opponent",placeholder="Team Name (ORG)",label_visibility="collapsed")
        if oa2.button("Add",type="primary") and no.strip():
            if add_db_opponent(el,no.strip()): st.success(f"Added {no.strip()}")
            else: st.warning("Already exists.")
            st.rerun()