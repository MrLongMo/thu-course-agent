#!/usr/bin/env python3
"""
Generate static index.html for GitHub Pages
"""
import json
import os
from flask import Flask, render_template

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

# Load data
DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'processed', 'courses_114_2.json')
with open(DATA_PATH, encoding='utf-8') as f:
    ALL_COURSES = json.load(f)

DEPARTMENTS = sorted(set(
    c.get('開課系所名稱', '').strip()
    for c in ALL_COURSES
    if c.get('開課系所名稱', '').strip()
))

# Create build directory
os.makedirs('build', exist_ok=True)

# Render template
with app.app_context():
    html = render_template('index.html', departments=DEPARTMENTS)

with open('build/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Static index.html generated")