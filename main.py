from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
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
    "latitude": 35.84706729510516,      # 회사 위도
    "longitude": 127.14263183020292,    # 회사 경도
    "radius_meters": 200,     # 출근 허용 반경
    "weekly_hours": 40,
    "default_in": "08:00",
    "default_out": "17:00"
}

# ==================== 데이터베이스 ====================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    if DATABASE_URL:
        # PostgreSQL (Render)
        import psycopg2
        from psycopg2.extras import RealDictCursor
        # Render는 postgres:// 대신 postgresql://를 사용
        db_url = DATABASE_URL.replace("postgres://", "postgresql://")
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn
    else:
        # SQLite (로컬)
        conn = sqlite3.connect('flextime.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def get_placeholder():
    """PostgreSQL은 %s, SQLite는 ?"""
    return "%s" if DATABASE_URL else "?"

def db_execute(cursor, query, params=None):
    """SQL 실행 - PostgreSQL/SQLite 호환"""
    if DATABASE_URL:
        # PostgreSQL: ? -> %s 변환
        query = query.replace("?", "%s")
        # user는 PostgreSQL 예약어이므로 "user"로 변환
        query = query.replace(" user ", ' "user" ')
        query = query.replace(" user(", ' "user"(')
        query = query.replace("(user ", '("user" ')
        query = query.replace(" user\n", ' "user"\n')
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    return cursor

def init_db():
    conn = get_db()
    c = conn.cursor()
    ph = get_placeholder()
    
    if DATABASE_URL:
        # PostgreSQL
        db_execute(c, '''CREATE TABLE IF NOT EXISTS team (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS "user" (
            id SERIAL PRIMARY KEY,
            team_id INTEGER,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            annual_leave_total REAL DEFAULT 15,
            annual_leave_used REAL DEFAULT 0
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            work_minutes INTEGER DEFAULT 0
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS schedule (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            planned_in TEXT DEFAULT '08:00',
            planned_out TEXT DEFAULT '17:00',
            UNIQUE(user_id, date)
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS leave (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            UNIQUE(user_id, date)
        )''')
    else:
        # SQLite
        db_execute(c, '''CREATE TABLE IF NOT EXISTS team (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            annual_leave_total REAL DEFAULT 15,
            annual_leave_used REAL DEFAULT 0,
            FOREIGN KEY (team_id) REFERENCES team(id)
        )''')
        
        # 기존 attendance 테이블이 UNIQUE 제약이 있으면 새로 만들기
        db_execute(c, "SELECT sql FROM sqlite_master WHERE type='table' AND name='attendance'")
        result = c.fetchone()
        
        if result and 'UNIQUE' in (result[0] or ''):
            db_execute(c, "ALTER TABLE attendance RENAME TO attendance_old")
            db_execute(c, '''CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                clock_in TEXT,
                clock_out TEXT,
                work_minutes INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user(id)
            )''')
            db_execute(c, "INSERT INTO attendance SELECT * FROM attendance_old")
            db_execute(c, "DROP TABLE attendance_old")
        elif not result:
            db_execute(c, '''CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                clock_in TEXT,
                clock_out TEXT,
                work_minutes INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user(id)
            )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            planned_in TEXT DEFAULT '08:00',
            planned_out TEXT DEFAULT '17:00',
            FOREIGN KEY (user_id) REFERENCES user(id),
            UNIQUE(user_id, date)
        )''')
        
        db_execute(c, '''CREATE TABLE IF NOT EXISTS leave (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user(id),
            UNIQUE(user_id, date)
        )''')
    
    # 기본 팀 생성
    try:
        db_execute(c, f"INSERT INTO team (name) VALUES ({ph})", ('개발팀',))
    except:
        pass
    try:
        db_execute(c, f"INSERT INTO team (name) VALUES ({ph})", ('기획팀',))
    except:
        pass
    try:
        db_execute(c, f"INSERT INTO team (name) VALUES ({ph})", ('연구팀',))
    except:
        pass
    
    # 기본 관리자 계정 생성 (팀 없음)
    admin_password = hashlib.sha256("123456".encode()).hexdigest()
    try:
        if DATABASE_URL:
            db_execute(c, f'''
                INSERT INTO "user" (name, email, password, team_id, role) 
                VALUES ({ph}, {ph}, {ph}, NULL, 'admin')
            ''', ('관리자', 'admin@jbuh.kr', admin_password))
        else:
            db_execute(c, f'''
                INSERT OR IGNORE INTO user (name, email, password, team_id, role) 
                VALUES ({ph}, {ph}, {ph}, NULL, 'admin')
            ''', ('관리자', 'admin@jbuh.kr', admin_password))
    except:
        pass
    
    # 기존 관리자 팀 NULL로 업데이트
    try:
        db_execute(c, "UPDATE user SET team_id = NULL WHERE role = 'admin'")
    except:
        pass
    
    conn.commit()
    return conn

init_db()

# ==================== Pydantic 모델 ====================
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    team_id: int = 1

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
    date: str
    planned_in: str
    planned_out: str

class LeaveRequest(BaseModel):
    user_id: int
    date: str
    type: str  # 'annual', 'half_am', 'half_pm'

class AttendanceUpdate(BaseModel):
    user_id: int
    date: str
    clock_in: Optional[str] = None
    clock_out: Optional[str] = None

class AnnualLeaveUpdate(BaseModel):
    user_id: int
    annual_leave_total: float

# ==================== 유틸리티 ====================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def calculate_distance(lat1, lon1, lat2, lon2):
    """두 좌표 간 거리 계산 (미터)"""
    R = 6371000  # 지구 반경 (미터)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def get_week_dates(target_date=None):
    """해당 주의 월~금 날짜 리스트 반환"""
    if target_date is None:
        target_date = get_kst_today()
    
    # 월요일 찾기
    monday = target_date - timedelta(days=target_date.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]

# ==================== API 엔드포인트 ====================

# --- 인증 ---
@app.post("/api/auth/register")
def register(user: UserRegister):
    conn = get_db()
    c = conn.cursor()
    try:
        db_execute(c, 
            "INSERT INTO user (name, email, password, team_id) VALUES (?, ?, ?, ?)",
            (user.name, user.email, hash_password(user.password), user.team_id)
        )
        conn.commit()
        user_id = c.lastrowid
        return {"success": True, "user_id": user_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")

@app.post("/api/auth/login")
def login(user: UserLogin):
    conn = get_db()
    c = conn.cursor()
    db_execute(c, 
        "SELECT id, name, email, team_id, role, annual_leave_total, annual_leave_used FROM user WHERE email = ? AND password = ?",
        (user.email, hash_password(user.password))
    )
    row = c.fetchone()
    if row:
        return {
            "success": True,
            "user": {
                "id": row["id"],
                "name": row["name"],
                "email": row["email"],
                "team_id": row["team_id"],
                "role": row["role"],
                "annual_leave_total": row["annual_leave_total"],
                "annual_leave_used": row["annual_leave_used"]
            }
        }
    raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸습니다")

@app.get("/api/auth/user/{user_id}")
def get_user(user_id: int):
    conn = get_db()
    c = conn.cursor()
    db_execute(c, 
        "SELECT u.*, t.name as team_name FROM user u LEFT JOIN team t ON u.team_id = t.id WHERE u.id = ?",
        (user_id,)
    )
    row = c.fetchone()
    if row:
        return dict(row)
    raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

# --- 팀 ---
@app.get("/api/teams")
def get_teams():
    conn = get_db()
    c = conn.cursor()
    db_execute(c, "SELECT * FROM team")
    return [dict(row) for row in c.fetchall()]

class TeamCreate(BaseModel):
    name: str

@app.post("/api/teams")
def create_team(data: TeamCreate):
    conn = get_db()
    c = conn.cursor()
    try:
        db_execute(c, "INSERT INTO team (name) VALUES (?)", (data.name,))
        conn.commit()
        return {"success": True, "id": c.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="이미 존재하는 팀 이름입니다")

@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int):
    conn = get_db()
    c = conn.cursor()
    # 팀에 소속된 직원이 있는지 확인
    db_execute(c, "SELECT COUNT(*) as cnt FROM user WHERE team_id = ?", (team_id,))
    count = c.fetchone()["cnt"]
    if count > 0:
        raise HTTPException(status_code=400, detail=f"이 팀에 {count}명의 직원이 있어 삭제할 수 없습니다")
    
    db_execute(c, "DELETE FROM team WHERE id = ?", (team_id,))
    conn.commit()
    return {"success": True}

# --- 출퇴근 ---
@app.post("/api/attendance/clock-in")
def clock_in(data: ClockIn):
    # GPS 거리 확인
    distance = calculate_distance(
        data.latitude, data.longitude,
        COMPANY_SETTINGS["latitude"], COMPANY_SETTINGS["longitude"]
    )
    
    if distance > COMPANY_SETTINGS["radius_meters"]:
        raise HTTPException(
            status_code=400, 
            detail=f"회사에서 너무 멀어요! (현재 거리: {int(distance)}m, 허용: {COMPANY_SETTINGS['radius_meters']}m)"
        )
    
    conn = get_db()
    c = conn.cursor()
    today = get_kst_today().isoformat()
    now = get_kst_now().strftime("%H:%M")
    
    # 오늘 아직 퇴근 안 한 기록이 있는지 확인
    db_execute(c, 
        "SELECT id FROM attendance WHERE user_id = ? AND date = ? AND clock_out IS NULL",
        (data.user_id, today)
    )
    existing = c.fetchone()
    
    if existing:
        raise HTTPException(status_code=400, detail="이미 출근 중이에요! 먼저 퇴근 버튼을 눌러주세요.")
    
    # 새로운 출근 기록 생성 (하루에 여러 번 가능)
    db_execute(c, 
        "INSERT INTO attendance (user_id, date, clock_in) VALUES (?, ?, ?)",
        (data.user_id, today, now)
    )
    conn.commit()
    return {"success": True, "clock_in": now, "message": "출근 완료!"}

@app.post("/api/attendance/clock-out")
def clock_out(data: ClockOut):
    conn = get_db()
    c = conn.cursor()
    today = get_kst_today().isoformat()
    now = get_kst_now().strftime("%H:%M")
    
    # 오늘 퇴근 안 한 가장 최근 출근 기록 찾기
    db_execute(c, 
        "SELECT id, clock_in FROM attendance WHERE user_id = ? AND date = ? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",
        (data.user_id, today)
    )
    row = c.fetchone()
    
    if not row:
        raise HTTPException(status_code=400, detail="먼저 출근 버튼을 눌러주세요!")
    
    # 근무시간 계산
    clock_in_time = datetime.strptime(row["clock_in"], "%H:%M")
    clock_out_time = datetime.strptime(now, "%H:%M")
    work_minutes = int((clock_out_time - clock_in_time).total_seconds() / 60)
    
    db_execute(c, 
        "UPDATE attendance SET clock_out = ?, work_minutes = ? WHERE id = ?",
        (now, work_minutes, row["id"])
    )
    conn.commit()
    
    hours = work_minutes // 60
    mins = work_minutes % 60
    return {
        "success": True, 
        "clock_out": now,
        "work_minutes": work_minutes,
        "message": f"퇴근 완료! 이번 세션 {hours}시간 {mins}분 근무 👏"
    }

@app.get("/api/attendance/today/{user_id}")
def get_today_attendance(user_id: int):
    try:
        conn = get_db()
        c = conn.cursor()
        today = get_kst_today().isoformat()
        
        # 오늘의 모든 출퇴근 기록 가져오기
        db_execute(c, 
            "SELECT * FROM attendance WHERE user_id = ? AND date = ? ORDER BY id",
            (user_id, today)
        )
        rows = c.fetchall()
        
        if not rows:
            return {"date": today, "clock_in": None, "clock_out": None, "work_minutes": 0, "sessions": [], "is_working": False}
        
        sessions = []
        total_minutes = 0
        current_session = None
        
        for row in rows:
            session = {
                "clock_in": row["clock_in"],
                "clock_out": row["clock_out"],
                "work_minutes": row["work_minutes"] or 0
            }
            sessions.append(session)
            total_minutes += row["work_minutes"] or 0
            
            # 아직 퇴근 안 한 세션이 있으면
            if row["clock_in"] and not row["clock_out"]:
                current_session = row
        
        result = {
            "date": today,
            "clock_in": rows[0]["clock_in"],  # 첫 출근 시간
            "clock_out": rows[-1]["clock_out"],  # 마지막 퇴근 시간
            "work_minutes": total_minutes,
            "sessions": sessions,
            "is_working": False
        }
        
        # 현재 근무중인 세션이 있으면 실시간 계산
        if current_session:
            try:
                clock_in_time = datetime.strptime(current_session["clock_in"], "%H:%M")
                now = get_kst_now()
                current_time = datetime.strptime(now.strftime("%H:%M"), "%H:%M")
                current_minutes = int((current_time - clock_in_time).total_seconds() / 60)
                result["current_minutes"] = current_minutes
                result["is_working"] = True
            except:
                result["is_working"] = True
                result["current_minutes"] = 0
        
        return result
    except Exception as e:
        print(f"Error in get_today_attendance: {e}")
        return {"date": "", "clock_in": None, "clock_out": None, "work_minutes": 0, "sessions": [], "is_working": False, "error": str(e)}

@app.get("/api/attendance/weekly/{user_id}")
def get_weekly_attendance(user_id: int):
    conn = get_db()
    c = conn.cursor()
    week_dates = get_week_dates()
    
    # 각 날짜별 총 근무시간 계산
    db_execute(c, 
        f"SELECT date, SUM(work_minutes) as total_minutes FROM attendance WHERE user_id = ? AND date IN ({','.join(['?']*5)}) GROUP BY date",
        [user_id] + week_dates
    )
    records = {row["date"]: row["total_minutes"] or 0 for row in c.fetchall()}
    
    # 오늘 현재 근무중인 세션 확인
    today = get_kst_today().isoformat()
    db_execute(c, 
        "SELECT clock_in FROM attendance WHERE user_id = ? AND date = ? AND clock_out IS NULL",
        (user_id, today)
    )
    working_session = c.fetchone()
    
    # 휴가 정보도 가져오기
    db_execute(c, 
        f"SELECT * FROM leave WHERE user_id = ? AND date IN ({','.join(['?']*5)})",
        [user_id] + week_dates
    )
    leaves = {row["date"]: dict(row) for row in c.fetchall()}
    
    total_minutes = 0
    daily = []
    
    for d in week_dates:
        minutes = records.get(d, 0)
        
        # 오늘이고 근무중이면 현재까지 시간 추가
        if d == today and working_session:
            clock_in_time = datetime.strptime(working_session["clock_in"], "%H:%M")
            now_time = datetime.strptime(get_kst_now().strftime("%H:%M"), "%H:%M")
            current_minutes = int((now_time - clock_in_time).total_seconds() / 60)
            minutes += current_minutes
        
        total_minutes += minutes
        
        leave_text = None
        if d in leaves:
            leave_text = {"annual": "연차", "half_am": "오전반차", "half_pm": "오후반차"}.get(leaves[d]["type"])
        
        daily.append({"date": d, "minutes": minutes, "leave": leave_text})
    
    return {
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "target_hours": COMPANY_SETTINGS["weekly_hours"],
        "progress_percent": min(100, round(total_minutes / 60 / COMPANY_SETTINGS["weekly_hours"] * 100)),
        "daily": daily
    }

@app.put("/api/attendance/update")
def update_attendance(data: AttendanceUpdate):
    conn = get_db()
    c = conn.cursor()
    
    # 기존 기록 확인
    db_execute(c, 
        "SELECT id, clock_in, clock_out FROM attendance WHERE user_id = ? AND date = ?",
        (data.user_id, data.date)
    )
    row = c.fetchone()
    
    if not row:
        # 기록이 없으면 새로 생성
        db_execute(c, 
            "INSERT INTO attendance (user_id, date, clock_in, clock_out) VALUES (?, ?, ?, ?)",
            (data.user_id, data.date, data.clock_in, data.clock_out)
        )
    else:
        # 기존 기록 업데이트
        new_clock_in = data.clock_in if data.clock_in else row["clock_in"]
        new_clock_out = data.clock_out if data.clock_out else row["clock_out"]
        
        # 근무시간 재계산
        work_minutes = 0
        if new_clock_in and new_clock_out:
            in_time = datetime.strptime(new_clock_in, "%H:%M")
            out_time = datetime.strptime(new_clock_out, "%H:%M")
            work_minutes = int((out_time - in_time).total_seconds() / 60)
        
        db_execute(c, 
            "UPDATE attendance SET clock_in = ?, clock_out = ?, work_minutes = ? WHERE id = ?",
            (new_clock_in, new_clock_out, work_minutes, row["id"])
        )
    
    conn.commit()
    return {"success": True, "message": "수정 완료!"}

# --- 일정 ---
@app.get("/api/schedule/week/{user_id}")
def get_week_schedule(user_id: int):
    conn = get_db()
    c = conn.cursor()
    week_dates = get_week_dates()
    
    db_execute(c, 
        f"SELECT * FROM schedule WHERE user_id = ? AND date IN ({','.join(['?']*5)})",
        [user_id] + week_dates
    )
    records = {row["date"]: dict(row) for row in c.fetchall()}
    
    result = []
    for d in week_dates:
        if d in records:
            result.append(records[d])
        else:
            result.append({
                "date": d,
                "planned_in": COMPANY_SETTINGS["default_in"],
                "planned_out": COMPANY_SETTINGS["default_out"]
            })
    
    return result

@app.put("/api/schedule/update")
def update_schedule(data: ScheduleUpdate):
    conn = get_db()
    c = conn.cursor()
    
    db_execute(c, 
        """INSERT INTO schedule (user_id, date, planned_in, planned_out) 
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, date) DO UPDATE SET 
           planned_in = excluded.planned_in, planned_out = excluded.planned_out""",
        (data.user_id, data.date, data.planned_in, data.planned_out)
    )
    conn.commit()
    return {"success": True}

# --- 팀 현황 ---
@app.get("/api/team/status/{team_id}")
def get_team_status(team_id: int, date: str = None):
    conn = get_db()
    c = conn.cursor()
    
    # 날짜 파라미터가 없으면 오늘
    if not date:
        target_date = get_kst_today().isoformat()
    else:
        target_date = date
    
    # 팀원 목록 (관리자 제외)
    db_execute(c, "SELECT id, name FROM user WHERE team_id = ? AND role != 'admin'", (team_id,))
    members = c.fetchall()
    
    result = []
    for member in members:
        # 출퇴근 기록
        db_execute(c, 
            "SELECT clock_in, clock_out FROM attendance WHERE user_id = ? AND date = ?",
            (member["id"], target_date)
        )
        attendance = c.fetchone()
        
        # 휴가 기록
        db_execute(c, 
            "SELECT type FROM leave WHERE user_id = ? AND date = ?",
            (member["id"], target_date)
        )
        leave = c.fetchone()
        
        # 일정
        db_execute(c, 
            "SELECT planned_in, planned_out FROM schedule WHERE user_id = ? AND date = ?",
            (member["id"], target_date)
        )
        schedule = c.fetchone()
        
        status = "미출근"
        leave_text = None
        if leave:
            leave_text = {"annual": "연차", "half_am": "오전반차", "half_pm": "오후반차"}.get(leave["type"], "휴가")
            status = leave_text
        elif attendance:
            if attendance["clock_out"]:
                status = "퇴근"
            else:
                status = "근무중"
        
        result.append({
            "id": member["id"],
            "name": member["name"],
            "status": status,
            "leave": leave_text,
            "clock_in": attendance["clock_in"] if attendance else None,
            "clock_out": attendance["clock_out"] if attendance else None,
            "planned_in": schedule["planned_in"] if schedule else COMPANY_SETTINGS["default_in"],
            "planned_out": schedule["planned_out"] if schedule else COMPANY_SETTINGS["default_out"]
        })
    
    return result

@app.get("/api/admin/all-status")
def get_all_status():
    """관리자용: 전체 직원 현황 (관리자 제외, 최종 출퇴근만)"""
    conn = get_db()
    c = conn.cursor()
    today = get_kst_today().isoformat()
    
    # 관리자 제외한 직원만 조회
    db_execute(c, """
        SELECT u.id, u.name, u.role, t.name as team_name
        FROM user u
        LEFT JOIN team t ON u.team_id = t.id
        WHERE u.role != 'admin'
    """)
    users = c.fetchall()
    
    result = []
    for user in users:
        # 최종 출퇴근 기록만 가져오기
        db_execute(c, """
            SELECT clock_in, clock_out, work_minutes 
            FROM attendance 
            WHERE user_id = ? AND date = ? 
            ORDER BY id DESC LIMIT 1
        """, (user["id"], today))
        att = c.fetchone()
        
        # 휴가 확인
        db_execute(c, "SELECT type FROM leave WHERE user_id = ? AND date = ?", (user["id"], today))
        leave = c.fetchone()
        
        status = "미출근"
        if leave:
            status = {"annual": "연차", "half_am": "오전반차", "half_pm": "오후반차"}.get(leave["type"], "휴가")
        elif att and att["clock_in"]:
            status = "퇴근" if att["clock_out"] else "근무중"
        
        result.append({
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "team": user["team_name"],
            "status": status,
            "clock_in": att["clock_in"] if att else None,
            "clock_out": att["clock_out"] if att else None,
            "work_minutes": att["work_minutes"] if att else 0
        })
    
    return result

@app.get("/api/admin/hours")
def get_admin_hours(period: str = "week"):
    """관리자용: 직원별 근무시간 (주간/월간)"""
    conn = get_db()
    c = conn.cursor()
    
    today = get_kst_today()
    
    if period == "week":
        # 이번 주 월~금
        monday = today - timedelta(days=today.weekday())
        dates = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    else:
        # 이번 달 1일 ~ 오늘
        first_day = today.replace(day=1)
        dates = [(first_day + timedelta(days=i)).isoformat() for i in range((today - first_day).days + 1)]
    
    # 모든 직원 목록
    db_execute(c, """
        SELECT u.id, u.name, t.name as team_name 
        FROM user u 
        LEFT JOIN team t ON u.team_id = t.id
        WHERE u.role != 'admin'
    """)
    users = c.fetchall()
    
    result = []
    for user in users:
        # 해당 기간 총 근무시간
        placeholders = ','.join(['?' for _ in dates])
        db_execute(c, f"""
            SELECT SUM(work_minutes) as total 
            FROM attendance 
            WHERE user_id = ? AND date IN ({placeholders})
        """, [user["id"]] + dates)
        
        row = c.fetchone()
        total_minutes = row["total"] or 0
        
        result.append({
            "id": user["id"],
            "name": user["name"],
            "team": user["team_name"],
            "total_minutes": total_minutes
        })
    
    # 근무시간 내림차순 정렬
    result.sort(key=lambda x: x["total_minutes"], reverse=True)
    
    return result

# --- 휴가 ---
@app.post("/api/leave")
def request_leave(data: LeaveRequest):
    conn = get_db()
    c = conn.cursor()
    
    # 연차 차감량 계산
    deduct = 1.0 if data.type == "annual" else 0.5
    
    # 잔여 연차 확인
    db_execute(c, "SELECT annual_leave_total, annual_leave_used FROM user WHERE id = ?", (data.user_id,))
    user = c.fetchone()
    remaining = user["annual_leave_total"] - user["annual_leave_used"]
    
    if remaining < deduct:
        raise HTTPException(status_code=400, detail=f"연차가 부족합니다! (잔여: {remaining}일)")
    
    try:
        db_execute(c, 
            "INSERT INTO leave (user_id, date, type) VALUES (?, ?, ?)",
            (data.user_id, data.date, data.type)
        )
        # 연차 사용량 업데이트
        db_execute(c, 
            "UPDATE user SET annual_leave_used = annual_leave_used + ? WHERE id = ?",
            (deduct, data.user_id)
        )
        conn.commit()
        return {"success": True, "message": "휴가가 등록되었습니다!"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="해당 날짜에 이미 휴가가 등록되어 있습니다")

@app.delete("/api/leave/{leave_id}")
def cancel_leave(leave_id: int):
    conn = get_db()
    c = conn.cursor()
    
    # 휴가 정보 가져오기
    db_execute(c, "SELECT user_id, type FROM leave WHERE id = ?", (leave_id,))
    leave = c.fetchone()
    
    if not leave:
        raise HTTPException(status_code=404, detail="휴가를 찾을 수 없습니다")
    
    # 연차 복원
    restore = 1.0 if leave["type"] == "annual" else 0.5
    
    db_execute(c, "DELETE FROM leave WHERE id = ?", (leave_id,))
    db_execute(c, 
        "UPDATE user SET annual_leave_used = annual_leave_used - ? WHERE id = ?",
        (restore, leave["user_id"])
    )
    conn.commit()
    
    return {"success": True, "message": "휴가가 취소되었습니다!"}

@app.get("/api/leave/my/{user_id}")
def get_my_leaves(user_id: int):
    conn = get_db()
    c = conn.cursor()
    db_execute(c, 
        "SELECT * FROM leave WHERE user_id = ? ORDER BY date DESC",
        (user_id,)
    )
    return [dict(row) for row in c.fetchall()]

@app.get("/api/leave/user-week/{user_id}")
def get_user_week_leaves(user_id: int):
    """특정 유저의 이번 주 휴가 목록"""
    conn = get_db()
    c = conn.cursor()
    week_dates = get_week_dates()
    
    db_execute(c, 
        f"SELECT * FROM leave WHERE user_id = ? AND date IN ({','.join(['?']*5)})",
        [user_id] + week_dates
    )
    return [dict(row) for row in c.fetchall()]

@app.put("/api/user/annual-leave")
def update_annual_leave(data: AnnualLeaveUpdate):
    conn = get_db()
    c = conn.cursor()
    db_execute(c, 
        "UPDATE user SET annual_leave_total = ? WHERE id = ?",
        (data.annual_leave_total, data.user_id)
    )
    conn.commit()
    return {"success": True}

class RoleUpdate(BaseModel):
    user_id: int
    role: str  # 'member' or 'admin'

@app.put("/api/user/role")
def update_user_role(data: RoleUpdate):
    conn = get_db()
    c = conn.cursor()
    db_execute(c, 
        "UPDATE user SET role = ? WHERE id = ?",
        (data.role, data.user_id)
    )
    conn.commit()
    role_name = "관리자" if data.role == "admin" else "일반 사용자"
    return {"success": True, "message": f"{role_name}로 변경되었습니다!"}

# --- 회사 설정 ---
@app.get("/api/settings")
def get_settings():
    return COMPANY_SETTINGS

class SettingsUpdate(BaseModel):
    latitude: float
    longitude: float
    radius_meters: int

@app.put("/api/settings")
def update_settings(data: SettingsUpdate):
    """회사 설정 업데이트"""
    global COMPANY_SETTINGS
    COMPANY_SETTINGS["latitude"] = data.latitude
    COMPANY_SETTINGS["longitude"] = data.longitude
    COMPANY_SETTINGS["radius_meters"] = data.radius_meters
    return {"success": True, "message": "설정이 저장되었습니다!"}

# --- 직원 관리 API ---
@app.get("/api/admin/employees")
def get_all_employees():
    """전체 직원 목록 (관리자 포함)"""
    conn = get_db()
    c = conn.cursor()
    db_execute(c, """
        SELECT u.id, u.name, u.email, u.role, u.team_id, t.name as team_name,
               u.annual_leave_total, u.annual_leave_used
        FROM user u
        LEFT JOIN team t ON u.team_id = t.id
        ORDER BY u.role DESC, u.name
    """)
    return [dict(row) for row in c.fetchall()]

@app.put("/api/admin/reset-password/{user_id}")
def reset_password(user_id: int):
    """비밀번호 초기화 (123456)"""
    conn = get_db()
    c = conn.cursor()
    new_password = hash_password("123456")
    db_execute(c, "UPDATE user SET password = ? WHERE id = ?", (new_password, user_id))
    conn.commit()
    return {"success": True, "message": "비밀번호가 123456으로 초기화되었습니다!"}

@app.get("/api/admin/attendance-detail/{user_id}")
def get_attendance_detail(user_id: int, date: str = None):
    """직원 출퇴근 상세 내역 (날짜별)"""
    conn = get_db()
    c = conn.cursor()
    target_date = date or get_kst_today().isoformat()
    
    # 해당 날짜의 모든 출퇴근 기록
    db_execute(c, """
        SELECT id, clock_in, clock_out, work_minutes 
        FROM attendance 
        WHERE user_id = ? AND date = ?
        ORDER BY id
    """, (user_id, target_date))
    sessions = [dict(row) for row in c.fetchall()]
    
    # 사용자 정보
    db_execute(c, "SELECT name FROM user WHERE id = ?", (user_id,))
    user = c.fetchone()
    
    # 총 근무 시간
    total_minutes = sum(s.get("work_minutes") or 0 for s in sessions)
    
    return {
        "user_id": user_id,
        "user_name": user["name"] if user else "",
        "date": target_date,
        "sessions": sessions,
        "total_minutes": total_minutes
    }

# ==================== 메인 페이지 ====================
@app.get("/", response_class=HTMLResponse)
def read_root():
    return open("templates/index.html", "r", encoding="utf-8").read()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
