#!/usr/bin/env bash
# Build the React dashboard into frontend/dist so Flask can serve it.
# Used by hosting platforms (Render blueprint) and locally before deploys.
set -euo pipefail
cd frontend
npm ci
npm run build
