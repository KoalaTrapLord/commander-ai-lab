#!/usr/bin/env python3
"""
Commander AI Lab — FastAPI Backend v3
═════════════════════════════════════

v3 adds:
  POST /api/lab/import/url       — Import deck from Archidekt/EDHREC URL
  POST /api/lab/import/text      — Import deck from card list text
  GET  /api/lab/meta/commanders  — List available commanders in meta mapping
  GET  /api/lab/meta/search      — Search commanders by name
  POST /api/lab/meta/fetch       — Fetch EDHREC average deck for a commander
  POST /api/lab/start            — Extended: accepts imported deck profiles

Runs on port 8080 by default. Serves the web UI static files at /.
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Request as FastAPIRequest
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    print("ERROR: FastAPI not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)
