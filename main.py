from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date as date_module, timedelta, timezone
import hashlib
import math
import os

# 한국 시간대
KST = timezone(timedelta(hours=9))

def get_kst_now():
    return datetime.now(KST)

def get_kst_today():
    return datetime.now(KST).date()

app = FastAPI(title="출근하자")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 회사 설정 ====================
COMPANY_SETTINGS = {
    "latitude": 35.84706729510516,
    "longitude": 127.14263183020292,
    "radius_meters": 200,
    "weekly_hours": 40,
    "default_in": "08:00",
    "default_out": "17:00"
}

# ==================== 데이터베이스 ====================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    if DATABASE_URL:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        db_url = DATABASE_URL.replace("postgres://", "postgresql://")
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect('flextime.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def execute_query(conn, query, params=None):
    """SQL 실행 - PostgreSQL/SQLite 호환"""
    c = conn.cursor()
    if DATABASE_URL:
        # PostgreSQL: ? -> %s, user -> "user"
        query = query.replace("?", "%s")
        query = query.replace(" user ", ' "user" ')
        query = query.replace(" user(", ' "user"(')
        query = query.replace("(user ", '("user" ')
    if params:
        c.execute(query, params)
    else:
        c.execute(query)
    return c

def init_db():
    conn = get_db()
    
    if DATABASE_URL:
        # PostgreSQL
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS team (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS "user" (
            id SERIAL PRIMARY KEY,
            team_id INTEGER,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            annual_leave_total REAL DEFAULT 15,
            annual_leave_used REAL DEFAULT 0
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            work_minutes INTEGER DEFAULT 0
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS schedule (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            planned_in TEXT DEFAULT '08:00',
            planned_out TEXT DEFAULT '17:00',
            UNIQUE(user_id, date)
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS leave (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            UNIQUE(user_id, date)
        )''')
    else:
        # SQLite
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS team (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            annual_leave_total REAL DEFAULT 15,
            annual_leave_used REAL DEFAULT 0
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            work_minutes INTEGER DEFAULT 0
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            planned_in TEXT DEFAULT '08:00',
            planned_out TEXT DEFAULT '17:00',
            UNIQUE(user_id, date)
        )''')
        
        execute_query(conn, '''CREATE TABLE IF NOT EXISTS leave (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            UNIQUE(user_id, date)
        )''')
    
    # 기본 팀 생성
    for team_name in ['개발팀', '기획팀', '연구팀']:
        try:
            execute_query(conn, "INSERT INTO team (name) VALUES (?)", (team_name,))
        except:
            pass
    
    # 기본 관리자 계정
    admin_pw = hashlib.sha256("123456".encode()).hexdigest()
    try:
        execute_query(conn, 
            "INSERT INTO user (name, email, password, team_id, role) VALUES (?, ?, ?, 1, ?)",
            ('관리자', 'admin@jbuh.kr', admin_pw, 'admin'))
    except:
        pass
    
    conn.commit()
    return conn

# 앱 시작 시 DB 초기화
init_db()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ==================== Pydantic 모델 ====================
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    team_id: int

class UserLogin(BaseModel):
    email: str
    password: str

class ClockIn(BaseModel):
    user_id: int
    latitude: float
    longitude: float

class ClockOut(BaseModel):
    user_id: int

class ScheduleUpdate(BaseModel):
    user_id: int
    schedules: list

class LeaveRequest(BaseModel):
    user_id: int
    date: str
    type: str

class TeamCreate(BaseModel):
    name: str

class RoleUpdate(BaseModel):
    user_id: int
    role: str

# ==================== 인증 API ====================
@app.post("/api/auth/register")
def register(user: UserRegister):
    conn = get_db()
    try:
        execute_query(conn,
            "INSERT INTO user (name, email, password, team_id) VALUES (?, ?, ?, ?)",
            (user.name, user.email, hash_password(user.password), user.team_id))
        conn.commit()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다")

@app.post("/api/auth/login")
def login(user: UserLogin):
    conn = get_db()
    c = execute_query(conn,
        "SELECT id, name, email, team_id, role, annual_leave_total, annual_leave_used FROM user WHERE email = ? AND password = ?",
        (user.email, hash_password(user.password)))
    row = c.fetchone()
    if row:
        return {
            "success": True,
            "user": dict(row)
        }
    raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다")

@app.get("/api/auth/user/{user_id}")
def get_user(user_id: int):
    conn = get_db()
    c = execute_query(conn, "SELECT * FROM user WHERE id = ?", (user_id,))
    row = c.fetchone()
    if row:
        return dict(row)
    raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

# ==================== 팀 API ====================
@app.get("/api/teams")
def get_teams():
    conn = get_db()
    c = execute_query(conn, "SELECT * FROM team")
    return [dict(row) for row in c.fetchall()]

@app.post("/api/teams")
def create_team(data: TeamCreate):
    conn = get_db()
    try:
        execute_query(conn, "INSERT INTO team (name) VALUES (?)", (data.name,))
        conn.commit()
        return {"success": True}
    except:
        raise HTTPException(status_code=400, detail="이미 존재하는 팀 이름입니다")

@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int):
    conn = get_db()
    c = execute_query(conn, "SELECT COUNT(*) as cnt FROM user WHERE team_id = ?", (team_id,))
    count = c.fetchone()["cnt"]
    if count > 0:
        raise HTTPException(status_code=400, detail=f"이 팀에 {count}명의 직원이 있어 삭제할 수 없습니다")
    execute_query(conn, "DELETE FROM team WHERE id = ?", (team_id,))
    conn.commit()
    return {"success": True}

# ==================== 거리 계산 ====================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ==================== 출퇴근 API ====================
@app.post("/api/attendance/clock-in")
def clock_in(data: ClockIn):
    distance = haversine(data.latitude, data.longitude, 
                        COMPANY_SETTINGS["latitude"], COMPANY_SETTINGS["longitude"])
    
    if distance > COMPANY_SETTINGS["radius_meters"]:
        raise HTTPException(status_code=400, detail=f"회사에서 너무 멀어요! ({int(distance)}m)")
    
    conn = get_db()
    today = get_kst_today().isoformat()
    now_time = get_kst_now().strftime("%H:%M")
    
    # 오늘 퇴근 안 한 기록이 있는지 확인
    c = execute_query(conn,
        "SELECT id FROM attendance WHERE user_id = ? AND date = ? AND clock_out IS NULL",
        (data.user_id, today))
    if c.fetchone():
        raise HTTPException(status_code=400, detail="이미 출근 중입니다")
    
    execute_query(conn,
        "INSERT INTO attendance (user_id, date, clock_in) VALUES (?, ?, ?)",
        (data.user_id, today, now_time))
    conn.commit()
    return {"success": True, "clock_in": now_time}

@app.post("/api/attendance/clock-out")
def clock_out(data: ClockOut):
    conn = get_db()
    today = get_kst_today().isoformat()
    now_time = get_kst_now().strftime("%H:%M")
    
    c = execute_query(conn,
        "SELECT id, clock_in FROM attendance WHERE user_id = ? AND date = ? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",
        (data.user_id, today))
    row = c.fetchone()
    
    if not row:
        raise HTTPException(status_code=400, detail="출근 기록이 없습니다")
    
    # 근무 시간 계산
    clock_in = datetime.strptime(row["clock_in"], "%H:%M")
    clock_out = datetime.strptime(now_time, "%H:%M")
    work_minutes = int((clock_out - clock_in).total_seconds() / 60)
    
    execute_query(conn,
        "UPDATE attendance SET clock_out = ?, work_minutes = ? WHERE id = ?",
        (now_time, work_minutes, row["id"]))
    conn.commit()
    return {"success": True, "clock_out": now_time, "work_minutes": work_minutes}

@app.get("/api/attendance/today/{user_id}")
def get_today_attendance(user_id: int):
    conn = get_db()
    today = get_kst_today().isoformat()
    
    c = execute_query(conn,
        "SELECT * FROM attendance WHERE user_id = ? AND date = ? ORDER BY id",
        (user_id, today))
    rows = c.fetchall()
    
    if not rows:
        return {"is_working": False, "sessions": [], "total_minutes": 0}
    
    sessions = [dict(r) for r in rows]
    total_minutes = sum(s.get("work_minutes") or 0 for s in sessions)
    is_working = sessions[-1].get("clock_out") is None
    
    return {
        "is_working": is_working,
        "sessions": sessions,
        "total_minutes": total_minutes,
        "current_clock_in": sessions[-1]["clock_in"] if is_working else None
    }

@app.get("/api/attendance/weekly/{user_id}")
def get_weekly_attendance(user_id: int):
    conn = get_db()
    today = get_kst_today()
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    
    result = []
    total = 0
    for d in dates:
        c = execute_query(conn,
            "SELECT SUM(work_minutes) as mins FROM attendance WHERE user_id = ? AND date = ?",
            (user_id, d))
        row = c.fetchone()
        mins = row["mins"] or 0
        total += mins
        result.append({"date": d, "minutes": mins})
    
    return {"days": result, "total_minutes": total}

# ==================== 일정 API ====================
@app.get("/api/schedule/{user_id}")
def get_schedule(user_id: int):
    conn = get_db()
    today = get_kst_today()
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    
    result = []
    for d in dates:
        c = execute_query(conn,
            "SELECT planned_in, planned_out FROM schedule WHERE user_id = ? AND date = ?",
            (user_id, d))
        row = c.fetchone()
        if row:
            result.append({"date": d, "planned_in": row["planned_in"], "planned_out": row["planned_out"]})
        else:
            result.append({"date": d, "planned_in": COMPANY_SETTINGS["default_in"], "planned_out": COMPANY_SETTINGS["default_out"]})
    return result

@app.post("/api/schedule")
def update_schedule(data: ScheduleUpdate):
    conn = get_db()
    for s in data.schedules:
        try:
            execute_query(conn,
                "INSERT INTO schedule (user_id, date, planned_in, planned_out) VALUES (?, ?, ?, ?)",
                (data.user_id, s["date"], s["planned_in"], s["planned_out"]))
        except:
            execute_query(conn,
                "UPDATE schedule SET planned_in = ?, planned_out = ? WHERE user_id = ? AND date = ?",
                (s["planned_in"], s["planned_out"], data.user_id, s["date"]))
    conn.commit()
    return {"success": True}

# ==================== 팀 현황 API ====================
@app.get("/api/team/status/{team_id}")
def get_team_status(team_id: int, date: str = None):
    conn = get_db()
    target_date = date or get_kst_today().isoformat()
    
    c = execute_query(conn,
        "SELECT id, name FROM user WHERE team_id = ? AND role != ?",
        (team_id, 'admin'))
    members = c.fetchall()
    
    result = []
    for m in members:
        c = execute_query(conn,
            "SELECT clock_in, clock_out FROM attendance WHERE user_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
            (m["id"], target_date))
        att = c.fetchone()
        
        c = execute_query(conn, "SELECT type FROM leave WHERE user_id = ? AND date = ?", (m["id"], target_date))
        leave = c.fetchone()
        
        c = execute_query(conn,
            "SELECT planned_in, planned_out FROM schedule WHERE user_id = ? AND date = ?",
            (m["id"], target_date))
        sched = c.fetchone()
        
        status = "미출근"
        if leave:
            status = {"annual": "연차", "half_am": "오전반차", "half_pm": "오후반차"}.get(leave["type"], "휴가")
        elif att:
            status = "퇴근" if att["clock_out"] else "근무중"
        
        result.append({
            "id": m["id"],
            "name": m["name"],
            "status": status,
            "clock_in": att["clock_in"] if att else None,
            "clock_out": att["clock_out"] if att else None,
            "planned_in": sched["planned_in"] if sched else COMPANY_SETTINGS["default_in"],
            "planned_out": sched["planned_out"] if sched else COMPANY_SETTINGS["default_out"]
        })
    return result

# ==================== 휴가 API ====================
@app.post("/api/leave")
def request_leave(data: LeaveRequest):
    conn = get_db()
    deduct = 1.0 if data.type == "annual" else 0.5
    
    c = execute_query(conn,
        "SELECT annual_leave_total, annual_leave_used FROM user WHERE id = ?",
        (data.user_id,))
    user = c.fetchone()
    remaining = user["annual_leave_total"] - user["annual_leave_used"]
    
    if remaining < deduct:
        raise HTTPException(status_code=400, detail=f"연차가 부족합니다! (잔여: {remaining}일)")
    
    try:
        execute_query(conn,
            "INSERT INTO leave (user_id, date, type) VALUES (?, ?, ?)",
            (data.user_id, data.date, data.type))
        execute_query(conn,
            "UPDATE user SET annual_leave_used = annual_leave_used + ? WHERE id = ?",
            (deduct, data.user_id))
        conn.commit()
        return {"success": True}
    except:
        raise HTTPException(status_code=400, detail="이미 해당 날짜에 휴가가 있습니다")

@app.get("/api/leave/my/{user_id}")
def get_my_leaves(user_id: int):
    conn = get_db()
    c = execute_query(conn,
        "SELECT * FROM leave WHERE user_id = ? ORDER BY date DESC",
        (user_id,))
    return [dict(r) for r in c.fetchall()]

@app.delete("/api/leave/{leave_id}")
def cancel_leave(leave_id: int):
    conn = get_db()
    c = execute_query(conn, "SELECT user_id, type FROM leave WHERE id = ?", (leave_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="휴가를 찾을 수 없습니다")
    
    deduct = 1.0 if row["type"] == "annual" else 0.5
    execute_query(conn, "DELETE FROM leave WHERE id = ?", (leave_id,))
    execute_query(conn,
        "UPDATE user SET annual_leave_used = annual_leave_used - ? WHERE id = ?",
        (deduct, row["user_id"]))
    conn.commit()
    return {"success": True}

@app.get("/api/leave/user-week/{user_id}")
def get_user_week_leave(user_id: int):
    conn = get_db()
    today = get_kst_today()
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    
    result = []
    for d in dates:
        c = execute_query(conn, "SELECT type FROM leave WHERE user_id = ? AND date = ?", (user_id, d))
        row = c.fetchone()
        result.append({"date": d, "type": row["type"] if row else None})
    return result

# ==================== 관리자 API ====================
@app.get("/api/admin/all-status")
def get_all_status():
    conn = get_db()
    today = get_kst_today().isoformat()
    
    c = execute_query(conn, """
        SELECT u.id, u.name, u.role, t.name as team_name
        FROM user u
        LEFT JOIN team t ON u.team_id = t.id
    """)
    users = c.fetchall()
    
    result = []
    for u in users:
        c = execute_query(conn,
            "SELECT clock_in, clock_out, work_minutes FROM attendance WHERE user_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
            (u["id"], today))
        att = c.fetchone()
        
        c = execute_query(conn, "SELECT type FROM leave WHERE user_id = ? AND date = ?", (u["id"], today))
        leave = c.fetchone()
        
        status = "미출근"
        if leave:
            status = {"annual": "연차", "half_am": "오전반차", "half_pm": "오후반차"}.get(leave["type"], "휴가")
        elif att:
            status = "퇴근" if att["clock_out"] else "근무중"
        
        result.append({
            "id": u["id"],
            "name": u["name"],
            "role": u["role"],
            "team": u["team_name"],
            "status": status,
            "clock_in": att["clock_in"] if att else None,
            "clock_out": att["clock_out"] if att else None,
            "work_minutes": att["work_minutes"] if att else 0
        })
    return result

@app.get("/api/admin/hours")
def get_admin_hours(period: str = "week"):
    conn = get_db()
    today = get_kst_today()
    
    if period == "week":
        monday = today - timedelta(days=today.weekday())
        dates = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    else:
        first_day = today.replace(day=1)
        dates = [(first_day + timedelta(days=i)).isoformat() for i in range((today - first_day).days + 1)]
    
    c = execute_query(conn, """
        SELECT u.id, u.name, t.name as team_name
        FROM user u
        LEFT JOIN team t ON u.team_id = t.id
        WHERE u.role != ?
    """, ('admin',))
    users = c.fetchall()
    
    result = []
    for u in users:
        total = 0
        for d in dates:
            c = execute_query(conn,
                "SELECT SUM(work_minutes) as mins FROM attendance WHERE user_id = ? AND date = ?",
                (u["id"], d))
            row = c.fetchone()
            total += row["mins"] or 0
        
        result.append({
            "id": u["id"],
            "name": u["name"],
            "team": u["team_name"],
            "total_minutes": total
        })
    
    result.sort(key=lambda x: x["total_minutes"], reverse=True)
    return result

@app.put("/api/user/role")
def update_user_role(data: RoleUpdate):
    conn = get_db()
    execute_query(conn, "UPDATE user SET role = ? WHERE id = ?", (data.role, data.user_id))
    conn.commit()
    return {"success": True, "message": f"{'관리자' if data.role == 'admin' else '일반 사용자'}로 변경되었습니다!"}

@app.put("/api/user/annual-leave")
def update_annual_leave(user_id: int, total: float):
    conn = get_db()
    execute_query(conn, "UPDATE user SET annual_leave_total = ? WHERE id = ?", (total, user_id))
    conn.commit()
    return {"success": True}

# ==================== 설정 API ====================
@app.get("/api/settings")
def get_settings():
    return COMPANY_SETTINGS

# ==================== 메인 페이지 ====================
@app.get("/", response_class=HTMLResponse)
def read_root():
    return open("templates/index.html", "r", encoding="utf-8").read()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
