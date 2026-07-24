#!/usr/bin/env python3
"""Starts the Pixel Forge web app in debug mode on port 5050
(kept off the Flask default 5000 to avoid clashing with other local
projects running at the same time).

Usage: source .venv/bin/activate && python run.sh
       (from the project root, after pip install -e ".[dev]")
"""
from pixelforge.webapp import create_app

if __name__ == "__main__":
    create_app().run(debug=True, port=5050)
