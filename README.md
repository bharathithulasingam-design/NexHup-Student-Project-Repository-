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

Set the required environment variables before starting the app:

```powershell
$env:SECRET_KEY = "<a long random secret>"
$env:DB_PASSWORD = "<your MySQL password>"
```

Optional database settings default to `localhost`, user `root`, and database `nexhup_db`. Override them with `DB_HOST`, `DB_USER`, and `DB_NAME` if needed.

Start the development server with:

```powershell
python app.py
```

Uploaded files, local environment files, and virtual environments are intentionally excluded from Git.
