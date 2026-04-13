import json
import os
import hashlib
from typing import Optional

DB_FILE = os.environ.get("DB_PATH", "data/db.json")


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        data = {"teachers": {}, "telegram_links": {}}
        save_db(data)
        return data
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data: dict):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Teacher ────────────────────────────────────────────────────────────────────

def add_teacher(login: str, password: str, fio: str) -> bool:
    db = load_db()
    if login in db["teachers"]:
        return False
    db["teachers"][login] = {
        "fio": fio,
        "password_hash": _hash(password),
        "students": []
    }
    save_db(db)
    return True


def verify_teacher(login: str, password: str) -> bool:
    db = load_db()
    teacher = db["teachers"].get(login)
    if not teacher:
        return False
    return teacher["password_hash"] == _hash(password)


def get_teacher(login: str) -> Optional[dict]:
    return load_db()["teachers"].get(login)


def get_all_teachers() -> dict:
    return load_db()["teachers"]


def delete_teacher(login: str) -> bool:
    db = load_db()
    if login not in db["teachers"]:
        return False
    del db["teachers"][login]
    db["telegram_links"] = {k: v for k, v in db["telegram_links"].items() if v != login}
    save_db(db)
    return True


def change_teacher_password(login: str, new_password: str) -> bool:
    db = load_db()
    if login not in db["teachers"]:
        return False
    db["teachers"][login]["password_hash"] = _hash(new_password)
    save_db(db)
    return True


# ── Telegram ↔ Teacher link ────────────────────────────────────────────────────

def link_telegram(telegram_id: int, teacher_login: str):
    db = load_db()
    db["telegram_links"][str(telegram_id)] = teacher_login
    save_db(db)


def unlink_telegram(telegram_id: int):
    db = load_db()
    db["telegram_links"].pop(str(telegram_id), None)
    save_db(db)


def get_teacher_by_telegram(telegram_id: int) -> Optional[str]:
    return load_db()["telegram_links"].get(str(telegram_id))


# ── Students (per-teacher) ─────────────────────────────────────────────────────

def get_students(teacher_login: str) -> list:
    return load_db()["teachers"].get(teacher_login, {}).get("students", [])


def add_student(teacher_login: str, fio: str, login: str, password: str,
                parent_login: str, parent_password: str) -> bool:
    db = load_db()
    teacher = db["teachers"].get(teacher_login)
    if not teacher:
        return False
    if any(s["login"] == login for s in teacher["students"]):
        return False
    teacher["students"].append({
        "fio": fio,
        "login": login,
        "password": password,
        "parent": {"login": parent_login, "password": parent_password}
    })
    save_db(db)
    return True


def delete_student(teacher_login: str, student_login: str) -> bool:
    db = load_db()
    teacher = db["teachers"].get(teacher_login)
    if not teacher:
        return False
    before = len(teacher["students"])
    teacher["students"] = [s for s in teacher["students"] if s["login"] != student_login]
    if len(teacher["students"]) < before:
        save_db(db)
        return True
    return False


def update_student(teacher_login: str, student_login: str, field: str, value: str) -> bool:
    db = load_db()
    teacher = db["teachers"].get(teacher_login)
    if not teacher:
        return False
    for s in teacher["students"]:
        if s["login"] == student_login:
            if field == "fio":
                s["fio"] = value
            elif field == "password":
                s["password"] = value
            elif field == "parent_login":
                s["parent"]["login"] = value
            elif field == "parent_password":
                s["parent"]["password"] = value
            save_db(db)
            return True
    return False


def get_student(teacher_login: str, student_login: str) -> Optional[dict]:
    for s in get_students(teacher_login):
        if s["login"] == student_login:
            return s
    return None
