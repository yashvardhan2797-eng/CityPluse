"""Application factory for CityPulse."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.config import get_settings
from backend.demo_data import get_demo_cities
from backend.database import test_connection
from backend.routes import _data_mode, api_bp

# Built React dashboard (frontend/dist). Present in production deploys and
# local builds; when missing, "/" falls back to the API discovery document.
_DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")


def create_app() -> Flask:
    """Create and configure the CityPulse Flask application."""
    logging.basicConfig(level=logging.INFO)
    app = Flask(__name__)
    settings = get_settings()
    app.config.update(
        DEBUG=settings.debug,
        DATABASE_URL=settings.database_url,
        SUPABASE_URL=settings.supabase_url,
        # Kept server-side only; never rendered into frontend bundles.
        SUPABASE_PUBLISHABLE_KEY=settings.supabase_publishable_key,
        JSON_SORT_KEYS=False,
        # Phase 4 hardening: reject oversized request bodies (all real API
        # payloads are tiny JSON documents). 413 is returned by Flask.
        MAX_CONTENT_LENGTH = 64 * 1024,
    )

    CORS(app, resources={r"/api/*": {"origins": settings.cors_origins or "*"}})

    app.register_blueprint(api_bp)

    @app.errorhandler(404)
    def not_found(_error):
        # App-level so unmatched /api/* routes also get JSON (blueprint-level
        # handlers only fire for errors raised *inside* matched routes).
        return jsonify({"error": "Not found", "phase": 1}), 404

    @app.errorhandler(500)
    def server_error(_error):  # pragma: no cover
        return jsonify({"error": "Internal server error"}), 500

    @app.get("/health")
    def health():
        """Phase 4: detailed health probe (never leaks secrets).

        Used by the dashboard and by deployment platforms. Reports database
        reachability, which optional integrations are configured, and counts
        of enabled/critical failing providers so the UI can never show a
        successful live-data status when a provider has failed.
        """
        settings = get_settings()
        mode, db_ok = _data_mode()
        try:
            from backend.database import fetch_provider_status
            status_rows = fetch_provider_status()[1] if db_ok else []
        except Exception:  # pragma: no cover - health must never 500
            status_rows = []
        configured = {
            "weather": settings.weather_enabled,
            "air_quality": bool(settings.openaq_api_key),
            "transit": bool(settings.transit_gtfs_rt_url),
            "incident": bool(settings.incidents_socrata_url),
        }
        enabled = [st for st, ok in configured.items() if ok]
        failing = [
            r.get("source_type") for r in status_rows
            if r.get("source_type") in enabled and r.get("last_error")
        ]
        return jsonify({
            "status": "ok" if db_ok else "degraded",
            "mode": mode,
            "database_reachable": db_ok,
            "providers_configured": len(enabled),
            "providers_failed": len(failing),
            "failing_sources": failing,
            "ai_configured": bool(settings.ai_api_key and settings.ai_base_url),
            "realtime_enabled": settings.realtime_enabled,
            "simulation_enabled": settings.simulation_enabled,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            # Honor TLS-terminating reverse proxies (Render/Railway/nginx).
            "secure": request.is_secure
            or request.headers.get("X-Forwarded-Proto", "").lower() == "https",
        })

    @app.get("/")
    def index():
        """Serve the built dashboard when present; else the API discovery doc."""
        if os.path.isdir(_DIST_DIR) and os.path.isfile(os.path.join(_DIST_DIR, "index.html")):
            return send_from_directory(_DIST_DIR, "index.html")
        mode, db_ok = _data_mode()
        return jsonify({
            "name": "CityPulse API",
            "phase": 1,
            "mode": mode,
            "database_reachable": db_ok,
            "cities": [c["id"] for c in get_demo_cities()],
            "endpoints": [
                "/api/health",
                "/api/cities",
                "/api/records?city=bengaluru",
                "/api/summary?city=bengaluru",
                "/api/chart/severity?city=bengaluru",
                "/api/settings",
            ],
            "note": "Demo mode returns clearly-labeled synthetic data.",
        })

    @app.get("/<path:asset_path>")
    def spa_assets(asset_path: str):
        """Static assets for the dashboard, with SPA fallback to index.html.

        API paths are excluded first: an unknown /api/* route must keep its
        JSON 404 (API clients never get HTML). send_from_directory guards
        against path traversal.
        """
        if asset_path == "health" or asset_path == "api" or asset_path.startswith("api/"):
            return jsonify({"error": "Not found", "phase": 1}), 404
        if os.path.isdir(_DIST_DIR):
            candidate = os.path.join(_DIST_DIR, asset_path)
            if os.path.isfile(candidate):
                return send_from_directory(_DIST_DIR, asset_path)
            if os.path.isfile(os.path.join(_DIST_DIR, "index.html")):
                return send_from_directory(_DIST_DIR, "index.html")
        return jsonify({"error": "Not found", "phase": 1}), 404

    return app
