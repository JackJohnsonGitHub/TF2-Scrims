"""Gunicorn / WSGI entrypoint. Run in the container as `gunicorn wsgi:app`.

The app is built here rather than at `app` package import, so importing `app.db` — the
seed script, the pytest preflight — does not connect to the store as a side effect.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Local convenience only; production serving goes through Gunicorn.
    app.run(host=app.config["HOST"], port=app.config["PORT"])
