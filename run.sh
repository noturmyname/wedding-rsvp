#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH="/root/.local/lib/python3.12/site-packages:${PYTHONPATH}"
python3 app.py
