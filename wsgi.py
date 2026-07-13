"""Gunicorn / WSGI entrypoint. Run in the container as `gunicorn wsgi:app`."""
from app import app

if __name__ == "__main__":
    # Local convenience only; production serving goes through Gunicorn.
    app.run(host=app.config["HOST"], port=app.config["PORT"])
