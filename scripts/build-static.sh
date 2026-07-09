#!/usr/bin/env bash
# Rebuild the shareable static web app end to end.
#
# 1. Exports a fresh snapshot of the graph from Neo4j to frontend/public/snapshot.json
# 2. Builds the frontend into frontend/dist/ (a self-contained static site)
#
# Requires: the Neo4j container running (docker compose up -d) and the Python
# venv installed (.venv). The built site needs no backend or database to run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "1/2  Exporting snapshot from Neo4j..."
.venv/bin/med-graph export --out frontend/public/snapshot.json

echo "2/2  Building frontend..."
npm --prefix frontend run build

echo
echo "Done. Built site is in:  frontend/dist/"
echo "Deploy to Vercel:        npx vercel deploy frontend/dist --prod"
