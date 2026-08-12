#!/usr/bin/env python3
"""
Свадебный сайт с RSVP формой.
Запуск: python3 app.py
Откройте http://127.0.0.1:5000
Админка: http://127.0.0.1:5000/admin  (пароль по умолчанию: wedding2026)
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response,
    g,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-to-something-random-in-production")

# === НАСТРОЙКИ (измените под себя) ===
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "wedding2026")
COUPLE_NAMES = "Вадим & Ясмин"
WEDDING_DATE = "27 февраля 2027"
WEDDING_PLACE = "Ресторан «Лотос», Приморский край, Спасск-Дальний"
# =====================================

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rsvp.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS guests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            side TEXT NOT NULL,
            attendance TEXT NOT NULL,
            adults INTEGER NOT NULL DEFAULT 1,
            children INTEGER NOT NULL DEFAULT 0,
            children_info TEXT,
            phone TEXT,
            email TEXT,
            comments TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    # На случай, если таблица уже была без столбца ip_address
    try:
        db.execute("ALTER TABLE guests ADD COLUMN ip_address TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass  # столбец уже есть
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return decorated


@app.route("/")
def index():
    return render_template(
        "index.html",
        couple_names=COUPLE_NAMES,
        wedding_date=WEDDING_DATE,
        wedding_place=WEDDING_PLACE,
    )


@app.route("/rsvp", methods=["POST"])
def rsvp():
    full_name = (request.form.get("full_name") or "").strip()
    side = request.form.get("side") or ""
    attendance = request.form.get("attendance") or ""
    adults = request.form.get("adults", "1")
    children = request.form.get("children", "0")
    children_info = (request.form.get("children_info") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = ""  # email убрали из формы
    comments = (request.form.get("comments") or "").strip()

    errors = []
    if not full_name:
        errors.append("Укажите ФИО")
   if side not in ("жених", "невеста", "общие"):
        errors.append("Выберите сторону")
    if attendance not in ("да", "нет", "возможно"):
        errors.append("Укажите, будете ли присутствовать")

    try:
        adults = max(0, int(adults))
        children = max(0, int(children))
    except ValueError:
        errors.append("Некорректное количество гостей")

    if errors:
        flash(" • ".join(errors), "error")
        return redirect(url_for("index") + "#rsvp")

    # IP гостя (чтобы с одного адреса можно было только один ответ)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    db = get_db()

    # Если с этого IP уже был ответ — удаляем старый
    was_updated = False
    existing = db.execute(
        "SELECT id FROM guests WHERE ip_address = ?", (ip,)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM guests WHERE ip_address = ?", (ip,))
        was_updated = True

    db.execute(
        """
        INSERT INTO guests
        (full_name, side, attendance, adults, children, children_info, phone, email, comments, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            full_name,
            side,
            attendance,
            adults,
            children,
            children_info,
            phone,
            email,
            comments,
            ip,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()

    return render_template(
        "success.html",
        couple_names=COUPLE_NAMES,
        full_name=full_name,
        attendance=attendance,
        was_updated=was_updated,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        flash("Неверный пароль", "error")
    return render_template("admin_login.html", couple_names=COUPLE_NAMES)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin():
    db = get_db()
    guests = db.execute(
        "SELECT * FROM guests ORDER BY created_at DESC"
    ).fetchall()

    # Статистика только по тем, кто идёт (да) или возможно
    confirmed = [g for g in guests if g["attendance"] == "да"]
    maybe = [g for g in guests if g["attendance"] == "возможно"]
    declined = [g for g in guests if g["attendance"] == "нет"]

    def sum_field(lst, field):
        return sum(g[field] for g in lst)

    stats = {
        "total_responses": len(guests),
        "confirmed_count": len(confirmed),
        "maybe_count": len(maybe),
        "declined_count": len(declined),
        "adults_confirmed": sum_field(confirmed, "adults"),
        "children_confirmed": sum_field(confirmed, "children"),
        "adults_maybe": sum_field(maybe, "adults"),
        "children_maybe": sum_field(maybe, "children"),
        "groom_side_adults": sum_field(
            [g for g in confirmed if g["side"] == "жених"], "adults"
        ),
        "groom_side_children": sum_field(
            [g for g in confirmed if g["side"] == "жених"], "children"
        ),
        "bride_side_adults": sum_field(
            [g for g in confirmed if g["side"] == "невеста"], "adults"
        ),
        "bride_side_children": sum_field(
            [g for g in confirmed if g["side"] == "невеста"], "children"
        ),
    }

    return render_template(
        "admin.html",
        guests=guests,
        stats=stats,
        couple_names=COUPLE_NAMES,
    )


@app.route("/admin/export")
@login_required
def export_csv():
    db = get_db()
    guests = db.execute("SELECT * FROM guests ORDER BY created_at").fetchall()

    lines = [
        "id;ФИО;Сторона;Присутствие;Взрослые;Дети;Инфо о детях;Телефон;Email;Комментарии;Дата ответа"
    ]
    for g in guests:
        row = [
            str(g["id"]),
            g["full_name"].replace(";", ","),
            g["side"],
            g["attendance"],
            str(g["adults"]),
            str(g["children"]),
            (g["children_info"] or "").replace(";", ",").replace("\n", " "),
            g["phone"] or "",
            g["email"] or "",
            (g["comments"] or "").replace(";", ",").replace("\n", " "),
            g["created_at"],
        ]
        lines.append(";".join(row))

    csv_content = "\ufeff" + "\n".join(lines)  # BOM for Excel
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=wedding_guests.csv"
        },
    )


@app.route("/admin/delete/<int:guest_id>", methods=["POST"])
@login_required
def delete_guest(guest_id):
    db = get_db()
    db.execute("DELETE FROM guests WHERE id = ?", (guest_id,))
    db.commit()
    flash("Запись удалена", "success")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print(f"  Свадебный сайт: {COUPLE_NAMES}")
    print("  Откройте: http://127.0.0.1:5000")
    print("  Админка:  http://127.0.0.1:5000/admin")
    print(f"  Пароль:   {ADMIN_PASSWORD}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
