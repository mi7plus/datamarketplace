#!/bin/bash
cd "$(dirname "$0")"
venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 3001