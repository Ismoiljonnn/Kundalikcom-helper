import os
import hashlib
from typing import Optional
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME   = "kundalik_bot"

_client = None
_db     = None


def _get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI)
        _db     = _client[DB_NAME]
    return _db


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Teacher ────────────────────────────────────────────────────────────────────

def add_teacher(login: str, password: str, fio: str) -> bool:
    col = _get_db()["teachers"]
    if col.find_one({"login": login}):
        return False
    col.insert_one({
        "login": login,
        "fio": fio,
        "password_hash": _hash(password),
        "students": []
    })
    return True


def verify_teacher(login: str, password: str) -> bool:
    col     = _get_db()["teachers"]
    teacher = col.find_one({"login": login})
    if not teacher:
        return False
    return teacher["password_hash"] == _hash(password)


def get_teacher(login: str) -> Optional[dict]:
    col     = _get_db()["teachers"]
    teacher = col.find_one({"login": login}, {"_id": 0})
    return teacher


def get_all_teachers() -> dict:
    col      = _get_db()["teachers"]
    teachers = col.find({}, {"_id": 0})
    return {t["login"]: t for t in teachers}


def delete_teacher(login: str) -> bool:
    col    = _get_db()["teachers"]
    result = col.delete_one({"login": login})
    if result.deleted_count == 0:
        return False
    _get_db()["telegram_links"].delete_many({"teacher_login": login})
    return True


def change_teacher_password(login: str, new_password: str) -> bool:
    col    = _get_db()["teachers"]
    result = col.update_one(
        {"login": login},
        {"$set": {"password_hash": _hash(new_password)}}
    )
    return result.modified_count > 0


# ── Telegram ↔ Teacher link ────────────────────────────────────────────────────

def link_telegram(telegram_id: int, teacher_login: str):
    col = _get_db()["telegram_links"]
    col.update_one(
        {"telegram_id": str(telegram_id)},
        {"$set": {"teacher_login": teacher_login}},
        upsert=True
    )


def unlink_telegram(telegram_id: int):
    _get_db()["telegram_links"].delete_one({"telegram_id": str(telegram_id)})


def get_teacher_by_telegram(telegram_id: int) -> Optional[str]:
    col  = _get_db()["telegram_links"]
    link = col.find_one({"telegram_id": str(telegram_id)})
    return link["teacher_login"] if link else None


# ── Students (per-teacher) ─────────────────────────────────────────────────────

def get_students(teacher_login: str) -> list:
    col     = _get_db()["teachers"]
    teacher = col.find_one({"login": teacher_login}, {"_id": 0})
    return teacher.get("students", []) if teacher else []


def add_student(teacher_login: str, fio: str, login: str, password: str,
                parent_login: str, parent_password: str) -> bool:
    col     = _get_db()["teachers"]
    teacher = col.find_one({"login": teacher_login})
    if not teacher:
        return False
    if any(s["login"] == login for s in teacher.get("students", [])):
        return False
    col.update_one(
        {"login": teacher_login},
        {"$push": {"students": {
            "fio": fio,
            "login": login,
            "password": password,
            "parent": {"login": parent_login, "password": parent_password}
        }}}
    )
    return True


def delete_student(teacher_login: str, student_login: str) -> bool:
    col    = _get_db()["teachers"]
    result = col.update_one(
        {"login": teacher_login},
        {"$pull": {"students": {"login": student_login}}}
    )
    return result.modified_count > 0


def update_student(teacher_login: str, student_login: str, field: str, value: str) -> bool:
    col        = _get_db()["teachers"]
    field_map  = {
        "fio":             "students.$.fio",
        "password":        "students.$.password",
        "parent_login":    "students.$.parent.login",
        "parent_password": "students.$.parent.password",
    }
    mongo_field = field_map.get(field)
    if not mongo_field:
        return False
    result = col.update_one(
        {"login": teacher_login, "students.login": student_login},
        {"$set": {mongo_field: value}}
    )
    return result.modified_count > 0


def get_student(teacher_login: str, student_login: str) -> Optional[dict]:
    for s in get_students(teacher_login):
        if s["login"] == student_login:
            return s
    return None