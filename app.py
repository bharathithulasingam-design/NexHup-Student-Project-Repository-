
import os
import json
import requests
import uuid
import zipfile
import smtplib
import mysql.connector
from dotenv import load_dotenv
from email.message import EmailMessage

from flask import (
    Flask, render_template, request, redirect,
    abort, flash, url_for, session, jsonify, send_from_directory, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

load_dotenv()

app = Flask(__name__)
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
AI_MODEL = "qwen2.5:3b"

app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("The SECRET_KEY environment variable must be set.")


def get_password_reset_serializer():
    return URLSafeTimedSerializer(app.secret_key)


def send_password_reset_email(email, reset_url):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not all((smtp_host, smtp_username, smtp_password)):
        raise RuntimeError("Password reset email is not configured.")

    message = EmailMessage()
    message["Subject"] = "Reset your NexHup password"
    message["From"] = os.environ.get("SMTP_FROM", smtp_username)
    message["To"] = email
    message.set_content(
        "We received a request to reset your NexHup password.\n\n"
        f"Reset your password: {reset_url}\n\n"
        "This link expires in one hour. If you did not request it, you can ignore this email."
    )

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


# Project files are stored outside Flask's public static directory so private
# project files can only be served after checking project visibility.
LEGACY_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
UPLOAD_FOLDER = os.path.join(app.instance_path, "uploads")
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
DOCUMENT_EXTENSIONS = {"pdf"}
SOURCE_EXTENSIONS = {"zip"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LEGACY_UPLOAD_FOLDER, exist_ok=True)

for legacy_filename in os.listdir(LEGACY_UPLOAD_FOLDER):
    legacy_path = os.path.join(LEGACY_UPLOAD_FOLDER, legacy_filename)
    if os.path.isfile(legacy_path):
        private_path = os.path.join(UPLOAD_FOLDER, legacy_filename)
        if os.path.exists(private_path):
            raise FileExistsError(
                f"Cannot migrate project file because the destination exists: "
                f"{private_path}"
            )
        os.replace(legacy_path, private_path)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def get_db_connection():
    db_password = os.environ.get("DB_PASSWORD")
    if not db_password:
        raise RuntimeError("The DB_PASSWORD environment variable must be set.")

    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=db_password,
        database=os.environ.get("DB_NAME", "nexhup_db")
    )


def ensure_project_columns(conn):
    cursor = conn.cursor()
    try:
        columns = (
            ("source_filename", "VARCHAR(255) NULL"),
            ("visibility", "VARCHAR(10) NOT NULL DEFAULT 'public'"),
        )
        for column_name, column_definition in columns:
            cursor.execute(
                "SHOW COLUMNS FROM projects LIKE %s",
                (column_name,)
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    f"ALTER TABLE projects ADD COLUMN {column_name} "
                    f"{column_definition}"
                )
                app.logger.info(
                    "Added the %s column to the projects table.",
                    column_name
                )
    finally:
        cursor.close()


@app.route("/robots.txt")
def robots_txt():
    sitemap_url = url_for("sitemap_xml", _external=True)
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /upload-project\n"
        "Disallow: /edit-project/\n"
        "Disallow: /project/\n"
        f"Sitemap: {sitemap_url}\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    public_urls = (
        url_for("home", _external=True),
        url_for("explore", _external=True),
        url_for("about", _external=True),
    )
    url_entries = "".join(
        f"<url><loc>{url}</loc></url>" for url in public_urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{url_entries}"
        "</urlset>"
    )
    return Response(xml, mimetype="application/xml")


@app.route("/")
def home():
    if not session.get("user_id"):
        return render_template("index.html")

    conn = None
    cursor = None
    own_projects = []
    project_count = 0
    dashboard_error = None

    try:
        conn = get_db_connection()
        ensure_project_columns(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) AS project_count FROM projects WHERE user_id = %s",
            (session["user_id"],)
        )
        project_count = cursor.fetchone()["project_count"]

        cursor.execute("""
            SELECT id, title, description, category, technologies,
                   image_filename, source_filename, visibility
            FROM projects
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 6
        """, (session["user_id"],))
        own_projects = cursor.fetchall()

        next_steps = {
            "web development": "Add responsive layouts and a clear sign-in flow.",
            "python": "Add automated tests and expose one feature through an API.",
            "python projects": "Add automated tests and expose one feature through an API.",
            "ai/ml": "Test your model on new examples and explain its predictions.",
            "mobile app": "Add offline support and test the interface on different screen sizes.",
            "java": "Add unit tests and separate the application into clear service layers.",
            "java projects": "Add unit tests and separate the application into clear service layers.",
        }
        for project in own_projects:
            category = project["category"].strip().lower()
            idea = next_steps.get(
                category,
                "Add a README, tests, and one feature based on user feedback."
            )
            project["next_idea"] = idea

    except mysql.connector.Error:
        app.logger.exception("Personal dashboard database error")
        dashboard_error = (
            "Your dashboard could not load your projects. Please try again shortly."
        )

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        "index.html",
        own_projects=own_projects,
        project_count=project_count,
        dashboard_error=dashboard_error
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )

            if cursor.fetchone():
                flash("Email already registered. Please login.", "error")
                return redirect(url_for("login"))

            password_hash = generate_password_hash(password)

            cursor.execute(
                """INSERT INTO users
                   (full_name, email, password_hash)
                   VALUES (%s, %s, %s)""",
                (name, email, password_hash)
            )

            conn.commit()
            flash("Account created successfully! Please login.", "success")
            return redirect(url_for("login"))

        except mysql.connector.Error:
            app.logger.exception("Registration database error")
            flash("Unable to register. Check the database connection.", "error")

        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                """SELECT id, full_name, email, password_hash
                   FROM users WHERE email = %s""",
                (email,)
            )

            user = cursor.fetchone()

            if user and check_password_hash(
                user["password_hash"], password
            ):
                session.clear()
                session["user_id"] = user["id"]
                session["user_name"] = user["full_name"]
                session["user_email"] = user["email"]

                flash("Login successful!", "success")
                return redirect(url_for("home"))

            flash("Invalid email or password.", "error")

        except mysql.connector.Error:
            app.logger.exception("Login database error")
            flash("Unable to login. Check the database connection.", "error")

        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        conn = None
        cursor = None

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, email FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            if user:
                token = get_password_reset_serializer().dumps(
                    {"user_id": user["id"]}, salt="password-reset"
                )
                reset_url = url_for("reset_password", token=token, _external=True)
                send_password_reset_email(user["email"], reset_url)

            flash(
                "If an account exists for that email address, a password reset link has been sent.",
                "success"
            )
            return redirect(url_for("forgot_password"))

        except (mysql.connector.Error, RuntimeError, smtplib.SMTPException):
            app.logger.exception("Password reset request error")
            flash(
                "We could not send a password reset email. Please try again later.",
                "error"
            )

        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        data = get_password_reset_serializer().loads(
            token,
            salt="password-reset",
            max_age=60 * 60
        )
    except (BadSignature, SignatureExpired):
        flash("This password reset link is invalid or has expired.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password:
            flash("Please enter a new password.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            conn = None
            cursor = None

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (generate_password_hash(password), data["user_id"])
                )
                conn.commit()
                flash("Your password has been reset. Please log in.", "success")
                return redirect(url_for("login"))

            except mysql.connector.Error:
                app.logger.exception("Password reset error")
                flash("We could not reset your password. Please try again.", "error")

            finally:
                if cursor:
                    cursor.close()
                if conn and conn.is_connected():
                    conn.close()

    return render_template("reset_password.html", token=token)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/explore")
def explore():
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        ensure_project_columns(conn)
        cursor = conn.cursor(dictionary=True)

        
        cursor.execute("""
            SELECT p.id, p.user_id, p.title, p.description,
                   p.category, p.github_link, p.image_filename,
                   p.source_filename,
                   u.full_name
            FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE p.visibility = 'public'
            ORDER BY p.created_at DESC
        """)

        projects = cursor.fetchall()

        return render_template("explore.html", projects=projects)


    except mysql.connector.Error:
        app.logger.exception("Explore page database error")
        flash("Unable to load projects.", "error")
        return render_template("explore.html", projects=[])

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/project/<int:project_id>/file/<file_type>")
def project_file(project_id, file_type):
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        ensure_project_columns(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT user_id, visibility, image_filename, document_filename
               FROM projects WHERE id = %s""",
            (project_id,)
        )
        project = cursor.fetchone()

        filenames = {
            "image": "image_filename",
            "document": "document_filename",
        }
        filename_column = filenames.get(file_type)
        if not project or not filename_column:
            abort(404)
        if (
            project["visibility"] == "private"
            and project["user_id"] != session.get("user_id")
        ):
            abort(404)

        filename = project.get(filename_column)
        if not filename:
            abort(404)

        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            filename,
            as_attachment=False
        )

    except mysql.connector.Error:
        app.logger.exception("Project file lookup failed")
        abort(500)

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/project/<int:project_id>/source")
def download_project_source(project_id):
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        ensure_project_columns(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT user_id, visibility, source_filename
               FROM projects WHERE id = %s""",
            (project_id,)
        )
        project = cursor.fetchone()

        if (
            not project
            or not project.get("source_filename")
            or (
                project["visibility"] == "private"
                and project["user_id"] != session.get("user_id")
            )
        ):
            abort(404)

        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            project["source_filename"],
            as_attachment=True,
            download_name="project-source.zip"
        )

    except mysql.connector.Error:
        app.logger.exception("Project source download lookup failed")
        abort(500)

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/upload-project", methods=["GET", "POST"])
def upload_project():
    if not session.get("user_id"):
        flash("Please login to upload a project.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        technologies = request.form.get("technologies", "").strip()
        visibility = request.form.get("visibility", "").strip()
        github_link = request.form.get("github_link", "").strip()
        demo_link = request.form.get("demo_link", "").strip()

        image = request.files.get("image")
        document = request.files.get("document")
        source_file = request.files.get("source_file")

        if not title or not description or not category or not technologies:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("upload_project"))

        if visibility not in {"public", "private"}:
            flash("Please choose whether the project is public or private.", "error")
            return redirect(url_for("upload_project"))

        image_filename = None
        document_filename = None
        source_filename = None

        try:
            conn = get_db_connection()
            ensure_project_columns(conn)

            if image and image.filename:
                ext = image.filename.rsplit(".", 1)[-1].lower()
                if "." not in image.filename or ext not in IMAGE_EXTENSIONS:
                    flash("Please upload a PNG, JPG, JPEG, or WEBP image.", "error")
                    return redirect(url_for("upload_project"))

                image_filename = f"{uuid.uuid4().hex}.{ext}"
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

            if document and document.filename:
                ext = document.filename.rsplit(".", 1)[-1].lower()
                if "." not in document.filename or ext not in DOCUMENT_EXTENSIONS:
                    flash("Please upload a PDF document.", "error")
                    return redirect(url_for("upload_project"))

                document_filename = f"{uuid.uuid4().hex}.{ext}"
                document.save(os.path.join(app.config["UPLOAD_FOLDER"], document_filename))

            if source_file and source_file.filename:
                ext = source_file.filename.rsplit(".", 1)[-1].lower()
                if "." not in source_file.filename or ext not in SOURCE_EXTENSIONS:
                    flash("Please upload the source files as a ZIP archive.", "error")
                    return redirect(url_for("upload_project"))

                if not zipfile.is_zipfile(source_file.stream):
                    flash("The source file must be a valid ZIP archive.", "error")
                    return redirect(url_for("upload_project"))

                source_file.stream.seek(0)
                source_filename = f"{uuid.uuid4().hex}.zip"
                source_file.save(
                    os.path.join(app.config["UPLOAD_FOLDER"], source_filename)
                )

            cursor = conn.cursor()

            cursor.execute(
                """INSERT INTO projects
                (user_id, title, description, category, technologies,
                 github_link, demo_link, image_filename, document_filename,
                 source_filename, visibility)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    session["user_id"], title, description, category,
                    technologies, github_link or None, demo_link or None,
                    image_filename, document_filename, source_filename,
                    visibility
                )
            )

            conn.commit()
            flash("Project uploaded successfully!", "success")
            destination = "home" if visibility == "private" else "explore"
            return redirect(url_for(destination))

        except mysql.connector.Error:
            app.logger.exception("Project upload failed")
            flash(
                "Upload failed while saving to the database. Check that the "
                "database account can update the projects table schema.",
                "error"
            )

        except OSError:
            app.logger.exception("Project files could not be saved")
            flash("Upload failed while saving the files. Please try again.", "error")

        finally:
            if "cursor" in locals() and cursor:
                cursor.close()
            if "conn" in locals() and conn and conn.is_connected():
                conn.close()

    return render_template("upload_project.html")


    

@app.route("/edit-project/<int:project_id>", methods=["GET", "POST"])
def edit_project(project_id):
    if not session.get("user_id"):
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        ensure_project_columns(conn)
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM projects WHERE id = %s AND user_id = %s",
            (project_id, session["user_id"])
        )
        project = cursor.fetchone()

        if not project:
            flash("Project not found or you cannot edit it.", "error")
            return redirect(url_for("explore"))

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            category = request.form.get("category", "").strip()
            technologies = request.form.get("technologies", "").strip()
            visibility = request.form.get("visibility", "").strip()
            github_link = request.form.get("github_link", "").strip()
            demo_link = request.form.get("demo_link", "").strip()

            image = request.files.get("image")
            document = request.files.get("document")
            source_file = request.files.get("source_file")

            image_filename = project.get("image_filename")
            document_filename = project.get("document_filename")
            source_filename = project.get("source_filename")

            if not title or not description or not category or not technologies:
                flash("Please fill in all required fields.", "error")
                return render_template("edit_project.html", project=project)

            if visibility not in {"public", "private"}:
                flash("Please choose whether the project is public or private.", "error")
                return render_template("edit_project.html", project=project)

            if image and image.filename:
                ext = image.filename.rsplit(".", 1)[-1].lower()
                if "." not in image.filename or ext not in IMAGE_EXTENSIONS:
                    flash("Please upload a PNG, JPG, JPEG, or WEBP image.", "error")
                    return render_template("edit_project.html", project=project)

                image_filename = f"{uuid.uuid4().hex}.{ext}"
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

            if document and document.filename:
                ext = document.filename.rsplit(".", 1)[-1].lower()
                if "." not in document.filename or ext not in DOCUMENT_EXTENSIONS:
                    flash("Please upload a PDF document.", "error")
                    return render_template("edit_project.html", project=project)

                document_filename = f"{uuid.uuid4().hex}.{ext}"
                document.save(os.path.join(app.config["UPLOAD_FOLDER"], document_filename))

            if source_file and source_file.filename:
                ext = source_file.filename.rsplit(".", 1)[-1].lower()
                if "." not in source_file.filename or ext not in SOURCE_EXTENSIONS:
                    flash("Please upload the source files as a ZIP archive.", "error")
                    return render_template("edit_project.html", project=project)

                if not zipfile.is_zipfile(source_file.stream):
                    flash("The source file must be a valid ZIP archive.", "error")
                    return render_template("edit_project.html", project=project)

                source_file.stream.seek(0)
                source_filename = f"{uuid.uuid4().hex}.zip"
                source_file.save(
                    os.path.join(app.config["UPLOAD_FOLDER"], source_filename)
                )

            cursor.execute("""
                UPDATE projects
                SET title = %s, description = %s, category = %s,
                    technologies = %s, github_link = %s, demo_link = %s,
                    image_filename = %s, document_filename = %s,
                    source_filename = %s, visibility = %s
                WHERE id = %s AND user_id = %s
            """, (
                title, description, category, technologies,
                github_link or None, demo_link or None,
                image_filename, document_filename, source_filename,
                visibility, project_id, session["user_id"]
            ))

            conn.commit()
            flash("Project updated successfully!", "success")
            destination = "home" if visibility == "private" else "explore"
            return redirect(url_for(destination))

        return render_template("edit_project.html", project=project)

    except mysql.connector.Error:
        app.logger.exception("Edit project database error")
        flash("Unable to edit the project.", "error")
        return redirect(url_for("explore"))

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


@app.route("/delete-project/<int:project_id>", methods=["POST"])
def delete_project(project_id):
    if not session.get("user_id"):
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM projects WHERE id = %s AND user_id = %s",
            (project_id, session["user_id"])
        )
        conn.commit()

        if cursor.rowcount:
            flash("Project deleted successfully.", "success")
        else:
            flash("Project not found or you cannot delete it.", "error")

    except mysql.connector.Error:
        app.logger.exception("Delete project database error")
        flash("Unable to delete the project.", "error")

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return redirect(url_for("explore"))


@app.route("/ai-description", methods=["POST"])
def ai_description():
    if not session.get("user_id"):
        return {"error": "Please login first."}, 401

    data = request.get_json(silent=True) or {}

    title = data.get("title", "").strip()
    category = data.get("category", "").strip()
    technologies = data.get("technologies", "").strip()

    if not title:
        return {"error": "Please enter a project title."}, 400

    prompt = f"""
    Write a clear, simple project description for a student project.
    Project title: {title}
    Category: {category}
    Technologies: {technologies}
    Do not invent features that were not provided.
    Return only the description.
    """

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": AI_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        response.raise_for_status()
        description = response.json().get("response", "").strip()

        return {"description": description}

    except requests.RequestException:
        app.logger.exception("Ollama AI request failed")
        return {"error": "AI is unavailable. Please check Ollama."}, 503



@app.route("/ai-assistance", methods=["POST"])
def ai_assistance():
    if "user_id" not in session:
        return jsonify({"error": "Please login first."}), 401

    data = request.get_json() or {}
    title = data.get("title", "").strip()
    category = data.get("category", "").strip()
    technologies = data.get("technologies", "").strip()

    if not title:
        return jsonify({"error": "Enter your project title first."}), 400

    prompt = f"""
Project: {title}
Category: {category}
Technologies: {technologies}

Return JSON only:
{{
  "technologies": ["technology1", "technology2", "technology3"],
  "ideas": ["idea1", "idea2", "idea3"],
  "tips": ["tip1", "tip2", "tip3"]
}}
Keep every suggestion short and relevant.
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": AI_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "10m",
                "options": {
                    "num_predict": 120,
                    "temperature": 0.3
                }
            },
            timeout=120
        )
        response.raise_for_status()

        result = response.json().get("response", "")
        suggestions = json.loads(result)

        return jsonify(suggestions)

    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return jsonify({
            "error": "AI suggestions failed. Please try again."
        }), 500




@app.route("/chatbot", methods=["POST"])
def chatbot():
    if not session.get("user_id"):
        return {"error": "Please login first."}, 401

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()

    if not message:
        return {"error": "Please type a message."}, 400

    prompt = f"""
You are NexHup, a student project assistant.
Answer in simple English in 2 to 3 short sentences.
Focus on student projects, coding, and technologies.
Question: {message}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": AI_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 60}
            },
            timeout=120
        )
        response.raise_for_status()

        answer = response.json().get("response", "").strip()
        return {"reply": answer}

    except requests.RequestException:
        app.logger.exception("Chatbot request failed")
        return {
            "error": "Chatbot is unavailable. Please check Ollama."
        }, 503


if __name__ == "__main__":
    app.run(debug=True)
