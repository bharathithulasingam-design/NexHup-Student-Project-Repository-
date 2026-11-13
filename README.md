# NexHup

NexHup is a Flask web application for browsing and sharing student projects. It uses MySQL for application data and Ollama for its AI chat feature.

## Requirements

- Python 3.10 or later
- MySQL with a `nexhup_db` database and the tables expected by `app.py`
- Ollama running locally for the AI chat feature

## Setup

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy the example file once:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set a long random value for `SECRET_KEY` and your MySQL password for `DB_PASSWORD`. Optional database settings default to `localhost`, user `root`, and database `nexhup_db`; override them with `DB_HOST`, `DB_USER`, and `DB_NAME` if needed. Keep `.env` private; it is excluded from Git.

After the one-time setup, start the development server normally:

```powershell
python app.py
```

Uploaded files, local environment files, and virtual environments are intentionally excluded from Git.
