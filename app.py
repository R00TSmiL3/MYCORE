"""
app.py – Flask application untuk Perpustakaan Kata (Arsip Rasa)
Menyediakan:
- API publik untuk showcase dengan filter tipe, sumber, tag, search
- Admin panel (login, CRUD entries, CRUD types)
- Halaman statistik: daftar tipe, sumber, tag + jumlah + sorting (A-Z, Z-A, newest, oldest, most, least)
- Keamanan: bcrypt, CSRF, rate limiting, session protection, IP blocking 10 detik untuk 403
"""

import os
import re
import time
import sqlite3
import logging
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, Blueprint, abort)
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# Muat variabel dari .env
load_dotenv()

# --------------------------------------------------------------------
# Konfigurasi Aplikasi
# --------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-change-me')
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

csrf = CSRFProtect(app)
limiter = Limiter(key_func=get_remote_address,
                  default_limits=["200 per day", "50 per hour"])
limiter.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'admin.login'
login_manager.session_protection = "strong"
login_manager.init_app(app)

# --------------------------------------------------------------------
# Database & Logging
# --------------------------------------------------------------------
DATABASE = 'library.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'Anonim',
            tags TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (type_id) REFERENCES types (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Insert tipe default jika tabel types kosong
    existing_types = conn.execute("SELECT COUNT(*) as cnt FROM types").fetchone()['cnt']
    if existing_types == 0:
        default_types = ['puisi', 'quote', 'psikologi']
        for t in default_types:
            conn.execute("INSERT INTO types (name) VALUES (?)", (t,))
    # Admin default
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    existing = conn.execute("SELECT id FROM users WHERE username = ?",
                            (admin_username,)).fetchone()
    if not existing:
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (admin_username, generate_password_hash(admin_password)))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# Logger untuk 403
forbidden_logger = logging.getLogger('forbidden')
forbidden_logger.setLevel(logging.INFO)
fh = logging.FileHandler('access_denied.log')
fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
forbidden_logger.addHandler(fh)

# IP Blocking 10 detik
blocked_ips = {}

def is_ip_blocked(ip):
    if ip in blocked_ips:
        if time.time() > blocked_ips[ip]:
            del blocked_ips[ip]
            return False
        return True
    return False

def block_ip(ip, duration=10):
    blocked_ips[ip] = time.time() + duration

@app.before_request
def check_block():
    ip = request.remote_addr
    if is_ip_blocked(ip):
        return render_template('403.html'), 403

# --------------------------------------------------------------------
# User Class
# --------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'])
    return None

# --------------------------------------------------------------------
# Error Handlers
# --------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('Token keamanan tidak valid. Silakan coba lagi.', 'error')
    return redirect(request.referrer or url_for('index'))

@app.errorhandler(403)
def forbidden(error):
    ip = request.remote_addr
    user_agent = request.user_agent.string if request.user_agent else 'Unknown'
    path = request.path
    log_msg = f"403 - IP: {ip} | Path: {path} | UA: {user_agent}"
    forbidden_logger.info(log_msg)
    if not is_ip_blocked(ip):
        block_ip(ip, 10)
    return render_template('403.html'), 403

# --------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------
def get_types():
    """Return list of type dicts."""
    conn = get_db()
    types = conn.execute("SELECT * FROM types ORDER BY name").fetchall()
    conn.close()
    return [{'id': t['id'], 'name': t['name']} for t in types]

def get_type_name(type_id):
    conn = get_db()
    row = conn.execute("SELECT name FROM types WHERE id = ?", (type_id,)).fetchone()
    conn.close()
    return row['name'] if row else 'unknown'

def parse_tags(tags_str):
    """Convert comma-separated tags to clean list."""
    if not tags_str:
        return []
    return sorted(list(set(t.strip().lower() for t in tags_str.split(',') if t.strip())))

# --------------------------------------------------------------------
# ROUTE PUBLIK
# --------------------------------------------------------------------
@app.route('/')
def index():
    types = get_types()
    return render_template('index.html', types=types)

@app.route('/api/entries')
def api_entries():
    """
    API publik dengan filter:
    - search : cari di content, source, tags
    - type   : id tipe
    - source : cari spesifik sumber
    - tag    : filter tag spesifik
    - sort   : newest, oldest, a-z, z-a (default newest)
    - page, per_page
    """
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type', '').strip()
    source_filter = request.args.get('source', '').strip()
    tag_filter = request.args.get('tag', '').strip()
    sort = request.args.get('sort', 'newest').strip()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 15, type=int)), 50)
    offset = (page - 1) * per_page

    conn = get_db()
    conditions = []
    params = []

    # Join dengan types untuk mendapatkan nama tipe
    query_base = "SELECT e.*, t.name as type_name FROM entries e JOIN types t ON e.type_id = t.id"
    count_base = "SELECT COUNT(*) as total FROM entries e JOIN types t ON e.type_id = t.id"

    if type_id and type_id.isdigit():
        conditions.append("e.type_id = ?")
        params.append(int(type_id))
    if search:
        conditions.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ?)")
        like_search = f"%{search}%"
        params.extend([like_search, like_search, like_search, like_search])
    if source_filter:
        conditions.append("e.source LIKE ?")
        params.append(f"%{source_filter}%")
    if tag_filter:
        conditions.append("e.tags LIKE ?")
        params.append(f"%{tag_filter}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Sorting
    order_map = {
        'newest': 'e.created_at DESC',
        'oldest': 'e.created_at ASC',
        'a-z': 'e.content COLLATE NOCASE ASC',
        'z-a': 'e.content COLLATE NOCASE DESC'
    }
    order_by = order_map.get(sort, 'e.created_at DESC')

    query = f"{query_base} {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
    query_params = params + [per_page, offset]
    entries = conn.execute(query, query_params).fetchall()

    count_query = f"{count_base} {where_clause}"
    total_row = conn.execute(count_query, params).fetchone()
    total = total_row['total'] if total_row else 0

    conn.close()

    result = []
    for e in entries:
        result.append({
            'id': e['id'],
            'type': e['type_name'],
            'type_id': e['type_id'],
            'content': e['content'],
            'source': e['source'] or 'Anonim',
            'tags': parse_tags(e['tags']),
            'created_at': e['created_at']
        })
    return jsonify({'entries': result, 'page': page, 'per_page': per_page, 'total': total})

@app.route('/api/stats')
def api_stats():
    """Statistik publik: jumlah per tipe, daftar sumber unik + jumlah, daftar tag + jumlah."""
    conn = get_db()
    types = conn.execute("SELECT t.id, t.name, COUNT(e.id) as cnt FROM types t LEFT JOIN entries e ON t.id = e.type_id GROUP BY t.id ORDER BY t.name").fetchall()
    sources = conn.execute("SELECT source, COUNT(*) as cnt FROM entries GROUP BY source ORDER BY source").fetchall()
    tags_rows = conn.execute("SELECT tags FROM entries WHERE tags != ''").fetchall()
    conn.close()

    tag_counts = {}
    for row in tags_rows:
        for tag in parse_tags(row['tags']):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

    return jsonify({
        'types': [{'id': t['id'], 'name': t['name'], 'count': t['cnt']} for t in types],
        'sources': [{'source': s['source'], 'count': s['cnt']} for s in sources if s['source']],
        'tags': [{'tag': tag, 'count': count} for tag, count in sorted_tags]
    })

# --------------------------------------------------------------------
# ADMIN BLUEPRINT
# --------------------------------------------------------------------
admin_bp = Blueprint('admin', __name__, url_prefix='/admin',
                     template_folder='templates/admin')

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated

# ----------------------- Login / Logout -----------------------
@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username dan password harus diisi.', 'error')
            return render_template('admin/login.html')
        conn = get_db()
        user_row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user_row and check_password_hash(user_row['password_hash'], password):
            login_user(User(user_row['id'], user_row['username']))
            flash('Berhasil login.', 'success')
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('admin.dashboard'))
        flash('Username atau password salah.', 'error')
    return render_template('admin/login.html')

@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('admin.login'))

# ----------------------- Dashboard Entries -----------------------
@admin_bp.route('/')
@admin_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    type_filter = request.args.get('type', '')
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'newest')

    conn = get_db()
    conditions = []
    params = []
    if type_filter and type_filter.isdigit():
        conditions.append("e.type_id = ?")
        params.append(int(type_filter))
    if search:
        conditions.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ?)")
        like_search = f"%{search}%"
        params.extend([like_search, like_search, like_search, like_search])

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    order_map = {
        'newest': 'e.created_at DESC',
        'oldest': 'e.created_at ASC',
        'a-z': 'e.content COLLATE NOCASE ASC',
        'z-a': 'e.content COLLATE NOCASE DESC'
    }
    order_by = order_map.get(sort, 'e.created_at DESC')

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM entries e JOIN types t ON e.type_id = t.id {where_clause}", params).fetchone()['cnt']
    entries = conn.execute(f"SELECT e.*, t.name as type_name FROM entries e JOIN types t ON e.type_id = t.id {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
    types = get_types()
    conn.close()
    return render_template('admin/dashboard.html', entries=entries, types=types,
                           page=page, total=total, per_page=per_page,
                           current_type=type_filter, current_search=search, current_sort=sort)

# ----------------------- CRUD Entries -----------------------
@admin_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add_entry():
    if request.method == 'POST':
        type_id = request.form.get('type_id', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip() or 'Anonim'
        tags_raw = request.form.get('tags', '')
        if not type_id or not content:
            flash('Tipe dan konten wajib diisi.', 'error')
            return render_template('admin/edit.html', entry=None, types=get_types())
        tags = ','.join(parse_tags(tags_raw))
        conn = get_db()
        conn.execute("INSERT INTO entries (type_id, content, source, tags) VALUES (?, ?, ?, ?)",
                     (int(type_id), content, source, tags))
        conn.commit()
        conn.close()
        flash('Entri berhasil ditambahkan.', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/edit.html', entry=None, types=get_types())

@admin_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_entry(id):
    conn = get_db()
    entry = conn.execute("SELECT * FROM entries WHERE id = ?", (id,)).fetchone()
    if not entry:
        conn.close()
        flash('Entri tidak ditemukan.', 'error')
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        type_id = request.form.get('type_id', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip() or 'Anonim'
        tags_raw = request.form.get('tags', '')
        if not type_id or not content:
            flash('Tipe dan konten wajib diisi.', 'error')
            conn.close()
            return render_template('admin/edit.html', entry=entry, types=get_types())
        tags = ','.join(parse_tags(tags_raw))
        conn.execute("UPDATE entries SET type_id=?, content=?, source=?, tags=? WHERE id=?",
                     (int(type_id), content, source, tags, id))
        conn.commit()
        conn.close()
        flash('Entri diperbarui.', 'success')
        return redirect(url_for('admin.dashboard'))
    conn.close()
    return render_template('admin/edit.html', entry=entry, types=get_types())

@admin_bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete_entry(id):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Entri dihapus.', 'info')
    return redirect(url_for('admin.dashboard'))

# ----------------------- CRUD Types -----------------------
@admin_bp.route('/types')
@admin_required
def list_types():
    sort = request.args.get('sort', 'a-z')
    order_map = {
        'a-z': 'name COLLATE NOCASE ASC',
        'z-a': 'name COLLATE NOCASE DESC',
        'newest': 'created_at DESC',
        'oldest': 'created_at ASC',
        'most': '(SELECT COUNT(*) FROM entries WHERE type_id = types.id) DESC',
        'least': '(SELECT COUNT(*) FROM entries WHERE type_id = types.id) ASC'
    }
    order = order_map.get(sort, 'name COLLATE NOCASE ASC')
    conn = get_db()
    types = conn.execute(f"""
        SELECT t.*, COUNT(e.id) as cnt
        FROM types t LEFT JOIN entries e ON t.id = e.type_id
        GROUP BY t.id
        ORDER BY {order}
    """).fetchall()
    conn.close()
    return render_template('admin/types.html', types=types, current_sort=sort)

@admin_bp.route('/types/add', methods=['POST'])
@admin_required
def add_type():
    name = request.form.get('name', '').strip().lower()
    if not name:
        flash('Nama tipe tidak boleh kosong.', 'error')
        return redirect(url_for('admin.list_types'))
    conn = get_db()
    exists = conn.execute("SELECT id FROM types WHERE name = ?", (name,)).fetchone()
    if exists:
        flash('Tipe sudah ada.', 'error')
    else:
        conn.execute("INSERT INTO types (name) VALUES (?)", (name,))
        conn.commit()
        flash('Tipe berhasil ditambahkan.', 'success')
    conn.close()
    return redirect(url_for('admin.list_types'))

@admin_bp.route('/types/edit/<int:id>', methods=['POST'])
@admin_required
def edit_type(id):
    name = request.form.get('name', '').strip().lower()
    if not name:
        flash('Nama tipe tidak boleh kosong.', 'error')
        return redirect(url_for('admin.list_types'))
    conn = get_db()
    conn.execute("UPDATE types SET name = ? WHERE id = ?", (name, id))
    conn.commit()
    conn.close()
    flash('Tipe diperbarui.', 'success')
    return redirect(url_for('admin.list_types'))

@admin_bp.route('/types/delete/<int:id>', methods=['POST'])
@admin_required
def delete_type(id):
    conn = get_db()
    # Cek apakah masih ada entri dengan tipe ini
    count = conn.execute("SELECT COUNT(*) as cnt FROM entries WHERE type_id = ?", (id,)).fetchone()['cnt']
    if count > 0:
        flash(f'Tidak bisa menghapus tipe yang masih memiliki {count} entri.', 'error')
    else:
        conn.execute("DELETE FROM types WHERE id = ?", (id,))
        conn.commit()
        flash('Tipe dihapus.', 'info')
    conn.close()
    return redirect(url_for('admin.list_types'))

# ----------------------- Halaman List Sumber & Tag (read only + sorting) -----------------------
@admin_bp.route('/sources')
@admin_required
def list_sources():
    sort = request.args.get('sort', 'a-z')
    order_map = {
        'a-z': 'source COLLATE NOCASE ASC',
        'z-a': 'source COLLATE NOCASE DESC',
        'most': 'cnt DESC',
        'least': 'cnt ASC'
    }
    order = order_map.get(sort, 'source COLLATE NOCASE ASC')
    conn = get_db()
    sources = conn.execute(f"""
        SELECT source, COUNT(*) as cnt
        FROM entries
        WHERE source != 'Anonim' AND source != ''
        GROUP BY source
        ORDER BY {order}
    """).fetchall()
    conn.close()
    return render_template('admin/sources.html', sources=sources, current_sort=sort)

@admin_bp.route('/tags')
@admin_required
def list_tags():
    sort = request.args.get('sort', 'a-z')
    conn = get_db()
    rows = conn.execute("SELECT tags FROM entries WHERE tags != ''").fetchall()
    conn.close()
    tag_counts = {}
    for row in rows:
        for tag in parse_tags(row['tags']):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sorted_tags = sorted(tag_counts.items())
    if sort == 'z-a':
        sorted_tags = sorted(tag_counts.items(), reverse=True)
    elif sort == 'most':
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    elif sort == 'least':
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1])
    return render_template('admin/tags.html', tags=[{'tag': t, 'count': c} for t, c in sorted_tags], current_sort=sort)

app.register_blueprint(admin_bp)

# --------------------------------------------------------------------
# Run
# --------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)