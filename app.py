from functools import wraps
import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-in-production"
init_db()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def current_user_context():
    return {"current_user": session.get("user_name"), "current_role": session.get("role")}


@app.route("/")
def index():
    with get_db() as db:
        internships = db.execute(
            """SELECT i.*, COALESCE(u.name, 'Partner Company') AS company_name,
                      c.company_name AS registered_company
               FROM internships i LEFT JOIN users u ON u.id = i.company_id
               LEFT JOIN companies c ON c.user_id = u.id
               ORDER BY i.created_at DESC LIMIT 6"""
        ).fetchall()
    return render_template("index.html", internships=internships)


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        if not name or not email or len(password) < 6 or role not in ("student", "company"):
            flash("Complete all fields. Password must contain at least 6 characters.", "error")
        else:
            try:
                with get_db() as db:
                    cursor = db.execute(
                        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), role),
                    )
                    if role == "student":
                        db.execute("INSERT INTO students (user_id) VALUES (?)", (cursor.lastrowid,))
                    else:
                        db.execute(
                            "INSERT INTO companies (user_id, company_name) VALUES (?, ?)",
                            (cursor.lastrowid, name),
                        )
                flash("Account created successfully. Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError as error:
                if "UNIQUE" in str(error).upper():
                    flash("That email address is already registered.", "error")
                else:
                    raise
    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE email = ?", (request.form.get("email", "").strip(),)
            ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], user_name=user["name"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    return redirect(url_for({"student": "student_dashboard", "company": "company_dashboard", "admin": "admin_dashboard"}[session["role"]]))


@app.route("/student")
@role_required("student")
def student_dashboard():
    with get_db() as db:
        profile = db.execute(
            """SELECT u.name, u.email, s.* FROM users u JOIN students s ON s.user_id = u.id
               WHERE u.id = ?""", (session["user_id"],)
        ).fetchone()
        internships = db.execute(
            """SELECT i.*, COALESCE(c.company_name, u.name, 'Partner Company') AS company_name,
                      a.id AS application_id, a.status AS application_status
               FROM internships i LEFT JOIN users u ON u.id = i.company_id
               LEFT JOIN companies c ON c.user_id = u.id
               LEFT JOIN applications a ON a.internship_id = i.id AND a.student_id = ?
               ORDER BY i.deadline ASC""", (session["user_id"],)
        ).fetchall()
        applications = db.execute(
            """SELECT a.*, i.title, COALESCE(c.company_name, u.name, 'Partner Company') AS company_name,
                      iv.interview_date, iv.result
               FROM applications a JOIN internships i ON i.id = a.internship_id
               LEFT JOIN users u ON u.id = i.company_id LEFT JOIN companies c ON c.user_id = u.id
               LEFT JOIN interviews iv ON iv.application_id = a.id
               WHERE a.student_id = ? ORDER BY a.applied_at DESC""", (session["user_id"],)
        ).fetchall()
    profile_skills = {
        skill.strip().lower()
        for skill in (profile["skills"] or "").replace(",", " ").split()
        if skill.strip()
    }
    department = (profile["department"] or "").lower()
    ranked_internships = []
    for internship in internships:
        searchable = " ".join(
            str(internship[field] or "").lower()
            for field in ("title", "description", "role", "technologies", "eligibility_criteria", "location")
        )
        skill_matches = sum(skill in searchable for skill in profile_skills)
        department_match = bool(department and department != "not specified" and department in searchable)
        try:
            cgpa_match = float(profile["cgpa"] or 0) >= 7 and "cgpa" in searchable
        except (TypeError, ValueError):
            cgpa_match = False
        match_score = skill_matches * 3 + int(department_match) * 2 + int(cgpa_match)
        ranked_internships.append((match_score, internship))
    ranked_internships.sort(key=lambda item: (-item[0], item[1]["deadline"]))
    recommended_internships = [item[1] for item in ranked_internships]
    return render_template(
        "student_dashboard.html",
        profile=profile,
        internships=recommended_internships,
        applications=applications,
    )


@app.route("/student/history")
@role_required("student")
def application_history():
    with get_db() as db:
        history = db.execute(
            """SELECT a.*, i.title, i.role, i.location,
                      COALESCE(c.company_name, u.name, 'Partner Company') AS company_name,
                      iv.interview_date, iv.result
               FROM applications a
               JOIN internships i ON i.id = a.internship_id
               LEFT JOIN users u ON u.id = i.company_id
               LEFT JOIN companies c ON c.user_id = u.id
               LEFT JOIN interviews iv ON iv.application_id = a.id
               WHERE a.student_id = ?
               ORDER BY a.applied_at DESC""",
            (session["user_id"],),
        ).fetchall()
    return render_template("application_history.html", history=history)


@app.post("/student/profile")
@role_required("student")
def update_student_profile():
    with get_db() as db:
        db.execute(
            """UPDATE students SET department = ?, cgpa = ?, skills = ?, phone = ?
               WHERE user_id = ?""",
            (
                request.form.get("department", "Not specified").strip(),
                request.form.get("cgpa", "0") or "0",
                request.form.get("skills", "").strip(),
                request.form.get("phone", "").strip(),
                session["user_id"],
            ),
        )
    flash("Profile updated.", "success")
    return redirect(url_for("student_dashboard"))


@app.post("/internships/<int:internship_id>/apply")
@role_required("student")
def apply(internship_id):
    with get_db() as db:
        try:
            db.execute("INSERT INTO applications (internship_id, student_id) VALUES (?, ?)", (internship_id, session["user_id"]))
            flash("Application submitted.", "success")
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error).upper():
                flash("You have already applied for this internship.", "error")
            else:
                raise
    return redirect(url_for("student_dashboard"))


@app.route("/company")
@role_required("company")
def company_dashboard():
    with get_db() as db:
        profile = db.execute(
            """SELECT u.email, c.* FROM users u JOIN companies c ON c.user_id = u.id
               WHERE u.id = ?""", (session["user_id"],)
        ).fetchone()
        internships = db.execute("SELECT * FROM internships WHERE company_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
        applications = db.execute(
            """SELECT a.*, i.title, u.name AS student_name, u.email AS student_email,
                      s.department, s.cgpa, iv.interview_date, iv.result
               FROM applications a JOIN internships i ON i.id = a.internship_id
               JOIN users u ON u.id = a.student_id LEFT JOIN students s ON s.user_id = u.id
               LEFT JOIN interviews iv ON iv.application_id = a.id
               WHERE i.company_id = ? ORDER BY a.applied_at DESC""", (session["user_id"],)
        ).fetchall()
    return render_template("company_dashboard.html", profile=profile, internships=internships, applications=applications)


@app.post("/company/profile")
@role_required("company")
def update_company_profile():
    with get_db() as db:
        db.execute(
            """UPDATE companies SET company_name = ?, location = ?, package = ?,
               eligibility_criteria = ? WHERE user_id = ?""",
            (request.form.get("company_name", "").strip(), request.form.get("location", "").strip(),
             request.form.get("package", "").strip(), request.form.get("eligibility_criteria", "").strip(),
             session["user_id"]),
        )
    flash("Company profile updated.", "success")
    return redirect(url_for("company_dashboard"))


@app.post("/company/internships")
@role_required("company")
def create_internship():
    fields = [request.form.get(key, "").strip() for key in
              ("title", "description", "location", "stipend", "deadline", "duration", "eligibility_criteria", "technologies", "package")]
    if not all(fields):
        flash("Complete every internship field.", "error")
    else:
        with get_db() as db:
            db.execute(
                """INSERT INTO internships
                   (company_id, title, description, location, stipend, deadline, role,
                    duration, eligibility_criteria, technologies, package)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session["user_id"], fields[0], fields[1], fields[2], fields[3], fields[4],
                 fields[0], fields[5], fields[6], fields[7], fields[8]),
            )
        flash("Internship published.", "success")
    return redirect(url_for("company_dashboard"))


@app.post("/company/applications/<int:application_id>/<status>")
@role_required("company")
def update_application(application_id, status):
    if status not in ("Shortlisted", "Rejected", "Selected"):
        flash("Invalid application status.", "error")
    else:
        with get_db() as db:
            db.execute(
                """UPDATE applications SET status = ? WHERE id = ? AND internship_id IN
                   (SELECT id FROM internships WHERE company_id = ?)""",
                (status, application_id, session["user_id"]),
            )
        flash("Application status updated.", "success")
    return redirect(url_for("company_dashboard"))


@app.post("/company/applications/<int:application_id>/interview")
@role_required("company")
def schedule_interview(application_id):
    with get_db() as db:
        db.execute(
            """INSERT INTO interviews (application_id, interview_date)
               SELECT ?, ? WHERE EXISTS
               (SELECT 1 FROM applications a JOIN internships i ON i.id = a.internship_id
                WHERE a.id = ? AND i.company_id = ?)""",
            (application_id, request.form.get("interview_date", "").strip(), application_id, session["user_id"]),
        )
    flash("Interview scheduled.", "success")
    return redirect(url_for("company_dashboard"))


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    with get_db() as db:
        stats = {
            "students": db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
            "companies": db.execute("SELECT COUNT(*) FROM users WHERE role='company'").fetchone()[0],
            "internships": db.execute("SELECT COUNT(*) FROM internships").fetchone()[0],
            "applications": db.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
        }
        users = db.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC").fetchall()
        placements = db.execute(
            """SELECT p.*, s.name AS student_name, c.name AS company_name
               FROM placements p JOIN users s ON s.id = p.student_id
               JOIN users c ON c.id = p.company_id ORDER BY p.joining_date"""
        ).fetchall()
    return render_template("admin_dashboard.html", stats=stats, users=users, placements=placements)


if __name__ == "__main__":
    app.run(debug=True)
