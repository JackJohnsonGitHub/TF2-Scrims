"""Flask application factory for the TF2 Server Hosting control plane.

Serves a server-rendered UI shell (feature 001) plus Steam sign-in and identity
(feature 002). Placeholder server data remains until real servers exist.
"""
from flask import Flask, render_template

from .config import Config
from .db import close_db, init_schema
from .security import current_user
from .timefmt import age_since, local_dt, pretty_utc


def create_app(config_object: type[Config] = Config) -> Flask:
    config_object.validate()

    app = Flask(__name__)
    app.config.from_object(config_object)

    # Initialize the metadata store (idempotent) and close connections per request.
    init_schema(app)
    app.teardown_appcontext(close_db)

    # Register blueprints (one per screen area).
    from .routes.health import bp as health_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.servers import bp as servers_bp
    from .routes.console import bp as console_bp
    from .routes.auth import bp as auth_bp
    from .routes.rgl import bp as rgl_bp
    from .routes.scrims import bp as scrims_bp
    from .routes.credits import bp as credits_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(servers_bp)
    app.register_blueprint(console_bp)
    app.register_blueprint(rgl_bp)
    app.register_blueprint(scrims_bp)
    app.register_blueprint(credits_bp)

    # CronJob-driven commands: payment polling and runtime-window expiry. Registered as
    # CLI commands rather than an in-process scheduler, because Gunicorn's two workers
    # would each run their own copy and race on crediting the same trade.
    from .cli import register as register_cli
    register_cli(app)

    # Expose the signed-in user to every template (header identity).
    @app.context_processor
    def inject_current_user():
        return {"current_user": current_user()}

    # Credit balance for the header box, on every page. Skipped entirely for anonymous
    # visitors so the landing page and error pages do no database work.
    #
    # Routes that need the number for their own logic (`can_extend`, `balance < 1`) still
    # compute it themselves. That is the same function in the same request, so the two
    # cannot disagree — it is one value read twice, not two sources of truth.
    @app.context_processor
    def inject_credit_balance():
        user = current_user()
        if not user:
            return {"credit_balance": None}
        from .credits import available_credits
        return {"credit_balance": available_credits(user["steam_id"])}

    # One time format across the scrims screens: UTC server-side, rewritten to the
    # viewer's timezone in the browser. Plus relative ages.
    app.jinja_env.filters["local_dt"] = local_dt
    app.jinja_env.filters["pretty_utc"] = pretty_utc
    app.jinja_env.filters["age_since"] = age_since

    # Friendly 404 for unknown addresses / unknown server ids.
    @app.errorhandler(404)
    def not_found(_err):
        return render_template("404.html"), 404

    return app


# Module-level app for `flask --app app run` and Gunicorn (`wsgi:app`).
app = create_app()
