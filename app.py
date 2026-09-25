"""CityPulse — Flask entrypoint.

Run (from the project root, virtual environment activated):

    python app.py

The API is served at http://127.0.0.1:5000  (health check: /api/health).
The React dashboard (frontend/) talks to this API via the /api prefix.
"""
import os

from backend import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=app.config.get("DEBUG", False),
    )
