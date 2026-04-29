import os, time, sqlite3, logging
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Blueprint, abort
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

csrf = CSRFProtect(app)
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])
limiter.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'admin.login'
login_manager.session_protection = "strong"
login_manager.init_app(app)

DATABASE = 'library.db'

# --------------------------------------------------------------------
# Database
# --------------------------------------------------------------------
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
            like_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (type_id) REFERENCES types (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            visitor_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entry_id, visitor_id),
            FOREIGN KEY (entry_id) REFERENCES entries (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Pastikan kolom like_count ada (upgrade dari versi lama)
    cols = [col[1] for col in conn.execute("PRAGMA table_info(entries)").fetchall()]
    if 'like_count' not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN like_count INTEGER DEFAULT 0")
    # Tipe default
    if conn.execute("SELECT COUNT(*) FROM types").fetchone()[0] == 0:
        for t in ['puisi', 'quote', 'psikologi']:
            conn.execute("INSERT INTO types (name) VALUES (?)", (t,))
    # Admin default
    admin_user = os.getenv('ADMIN_USERNAME', 'admin')
    if not conn.execute("SELECT id FROM users WHERE username = ?", (admin_user,)).fetchone():
        admin_pass = os.getenv('ADMIN_PASSWORD', 'admin123')
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (admin_user, generate_password_hash(admin_pass)))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# --------------------------------------------------------------------
# Logging & IP Blocker
# --------------------------------------------------------------------
forbidden_logger = logging.getLogger('forbidden')
forbidden_logger.setLevel(logging.INFO)
fh = logging.FileHandler('access_denied.log')
fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
forbidden_logger.addHandler(fh)

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
# User & Login
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
    flash('Token keamanan tidak valid.', 'error')
    return redirect(request.referrer or url_for('index'))
@app.errorhandler(403)
def forbidden(error):
    ip = request.remote_addr
    ua = request.user_agent.string if request.user_agent else 'Unknown'
    forbidden_logger.info(f"403 - IP: {ip} | Path: {request.path} | UA: {ua}")
    if not is_ip_blocked(ip):
        block_ip(ip, 10)
    return render_template('403.html'), 403

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def get_types():
    conn = get_db()
    types = conn.execute("SELECT * FROM types ORDER BY name").fetchall()
    conn.close()
    return [{'id': t['id'], 'name': t['name']} for t in types]

def parse_tags(tags_str):
    if not tags_str:
        return []
    return sorted(list(set(t.strip().lower() for t in tags_str.split(',') if t.strip())))

# ====================================================================
# PUBLIC ROUTES
# ====================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/entries')
def api_entries():
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type', '').strip()
    source = request.args.get('source', '').strip()
    tag = request.args.get('tag', '').strip()
    sort = request.args.get('sort', 'newest').strip()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 15, type=int)), 50)
    offset = (page - 1) * per_page
    visitor_id = request.args.get('visitor_id', '').strip()

    conn = get_db()
    base = "SELECT e.*, t.name as type_name FROM entries e JOIN types t ON e.type_id = t.id"
    conds = []
    params = []
    if type_id and type_id.isdigit():
        conds.append("e.type_id = ?")
        params.append(int(type_id))
    if search:
        conds.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ?)")
        params.extend([f"%{search}%"]*4)
    if source:
        conds.append("e.source LIKE ?")
        params.append(f"%{source}%")
    if tag:
        conds.append("e.tags LIKE ?")
        params.append(f"%{tag}%")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    order_map = {
        'newest': 'e.created_at DESC',
        'oldest': 'e.created_at ASC',
        'a-z': 'e.content COLLATE NOCASE ASC',
        'z-a': 'e.content COLLATE NOCASE DESC',
        'most_likes': 'e.like_count DESC',
        'least_likes': 'e.like_count ASC'
    }
    order = order_map.get(sort, 'e.created_at DESC')

    query = f"{base} {where} ORDER BY {order} LIMIT ? OFFSET ?"
    entries = conn.execute(query, params + [per_page, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) as cnt FROM entries e JOIN types t ON e.type_id = t.id {where}", params).fetchone()['cnt']

    liked_set = set()
    if visitor_id:
        entry_ids = [e['id'] for e in entries]
        if entry_ids:
            placeholders = ','.join('?'*len(entry_ids))
            liked_rows = conn.execute(
                f"SELECT entry_id FROM likes WHERE visitor_id = ? AND entry_id IN ({placeholders})",
                [visitor_id] + entry_ids
            ).fetchall()
            liked_set = {row['entry_id'] for row in liked_rows}

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
            'like_count': e['like_count'],
            'user_liked': e['id'] in liked_set,
            'created_at': e['created_at']
        })
    return jsonify({'entries': result, 'page': page, 'per_page': per_page, 'total': total})

@app.route('/api/entries/<int:entry_id>/like', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute;100 per hour")
def like_entry(entry_id):
    data = request.get_json(silent=True) or {}
    visitor_id = data.get('visitor_id', '').strip()
    if not visitor_id or len(visitor_id) < 8:
        return jsonify({'error': 'visitor_id tidak valid (min 8 karakter)'}), 400

    conn = get_db()
    try:
        entry = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            conn.close()
            return jsonify({'error': 'Entri tidak ditemukan'}), 404

        existing = conn.execute("SELECT id FROM likes WHERE entry_id = ? AND visitor_id = ?",
                                (entry_id, visitor_id)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Anda sudah menyukai entri ini'}), 409

        conn.execute("INSERT INTO likes (entry_id, visitor_id) VALUES (?, ?)", (entry_id, visitor_id))
        conn.execute("UPDATE entries SET like_count = like_count + 1 WHERE id = ?", (entry_id,))
        conn.commit()
        new_count = conn.execute("SELECT like_count FROM entries WHERE id = ?", (entry_id,)).fetchone()['like_count']
        app.logger.info(f"Like berhasil: entry {entry_id}, visitor {visitor_id}, total {new_count}")
        return jsonify({'success': True, 'like_count': new_count})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Kesalahan database (mungkin duplikat)'}), 409
    except Exception as e:
        app.logger.error(f"Unexpected error like: {e}")
        return jsonify({'error': 'Kesalahan server'}), 500
    finally:
        conn.close()

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    types = conn.execute("SELECT t.id, t.name, COUNT(e.id) as cnt FROM types t LEFT JOIN entries e ON t.id = e.type_id GROUP BY t.id ORDER BY t.name").fetchall()
    sources = conn.execute("SELECT source, COUNT(*) as cnt FROM entries WHERE source != 'Anonim' AND source != '' GROUP BY source ORDER BY source").fetchall()
    tag_rows = conn.execute("SELECT tags FROM entries WHERE tags != ''").fetchall()
    top_liked = conn.execute("SELECT id, content, like_count FROM entries ORDER BY like_count DESC LIMIT 5").fetchall()
    conn.close()

    tag_counts = {}
    for r in tag_rows:
        for t in parse_tags(r['tags']):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

    return jsonify({
        'types': [{'id': t['id'], 'name': t['name'], 'count': t['cnt']} for t in types],
        'sources': [{'source': s['source'], 'count': s['cnt']} for s in sources],
        'tags': [{'tag': tag, 'count': cnt} for tag, cnt in sorted_tags],
        'top_liked': [{'id': e['id'], 'content': e['content'][:80], 'likes': e['like_count']} for e in top_liked]
    })

# ====================================================================
# ADMIN BLUEPRINT
# ====================================================================
admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates/admin')

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.admin_index'))
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
            return redirect(url_for('admin.admin_index'))
        flash('Username atau password salah.', 'error')
    return render_template('admin/login.html')

@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/')
@login_required
def admin_index():
    return render_template('admin/admin.html')

# ====================================================================
# API ADMIN (dengan @csrf.exempt untuk POST/PUT/DELETE)
# ====================================================================

# --- Entries ---
@app.route('/api/admin/entries', methods=['GET'])
@login_required
def api_admin_entries():
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type', '').strip()
    sort = request.args.get('sort', 'newest').strip()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 100)
    offset = (page-1)*per_page

    conn = get_db()
    base = "SELECT e.*, t.name as type_name FROM entries e JOIN types t ON e.type_id = t.id"
    conds = []
    params = []
    if type_id and type_id.isdigit():
        conds.append("e.type_id = ?")
        params.append(int(type_id))
    if search:
        conds.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ?)")
        params.extend([f"%{search}%"]*4)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    order_map = {
        'newest': 'e.created_at DESC',
        'oldest': 'e.created_at ASC',
        'a-z': 'e.content COLLATE NOCASE ASC',
        'z-a': 'e.content COLLATE NOCASE DESC',
        'most_likes': 'e.like_count DESC',
        'least_likes': 'e.like_count ASC'
    }
    order = order_map.get(sort, 'e.created_at DESC')
    total = conn.execute(f"SELECT COUNT(*) as cnt FROM entries e JOIN types t ON e.type_id = t.id {where}", params).fetchone()['cnt']
    entries = conn.execute(f"{base} {where} ORDER BY {order} LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
    conn.close()

    result = []
    for e in entries:
        result.append({
            'id': e['id'],
            'type_id': e['type_id'],
            'type_name': e['type_name'],
            'content': e['content'],
            'source': e['source'] or 'Anonim',
            'tags': e['tags'],
            'like_count': e['like_count'],
            'created_at': e['created_at']
        })
    return jsonify({'entries': result, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/admin/entries', methods=['POST'])
@csrf.exempt
@login_required
def api_admin_create_entry():
    data = request.get_json()
    if not data or not data.get('type_id') or not data.get('content'):
        return jsonify({'error': 'type_id dan content diperlukan'}), 400
    type_id = int(data['type_id'])
    content = data['content'].strip()
    source = data.get('source', '').strip() or 'Anonim'
    tags_raw = data.get('tags', '')
    tags = ','.join(parse_tags(tags_raw))
    conn = get_db()
    cursor = conn.execute("INSERT INTO entries (type_id, content, source, tags, like_count) VALUES (?,?,?,?,0)",
                          (type_id, content, source, tags))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': new_id}), 201

@app.route('/api/admin/entries/<int:id>', methods=['GET'])
@login_required
def api_admin_get_entry(id):
    conn = get_db()
    entry = conn.execute("SELECT * FROM entries WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not entry:
        return jsonify({'error': 'Entri tidak ditemukan'}), 404
    return jsonify({
        'id': entry['id'],
        'type_id': entry['type_id'],
        'content': entry['content'],
        'source': entry['source'],
        'tags': entry['tags']
    })

@app.route('/api/admin/entries/<int:id>', methods=['PUT'])
@csrf.exempt
@login_required
def api_admin_update_entry(id):
    data = request.get_json()
    if not data or not data.get('type_id') or not data.get('content'):
        return jsonify({'error': 'type_id dan content diperlukan'}), 400
    type_id = int(data['type_id'])
    content = data['content'].strip()
    source = data.get('source', '').strip() or 'Anonim'
    tags_raw = data.get('tags', '')
    tags = ','.join(parse_tags(tags_raw))
    conn = get_db()
    conn.execute("UPDATE entries SET type_id=?, content=?, source=?, tags=? WHERE id=?",
                 (type_id, content, source, tags, id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/entries/<int:id>', methods=['DELETE'])
@csrf.exempt
@login_required
def api_admin_delete_entry(id):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Types ---
@app.route('/api/admin/types', methods=['GET'])
@login_required
def api_admin_types():
    sort = request.args.get('sort', 'a-z')
    order_map = {
        'a-z': 't.name COLLATE NOCASE ASC',
        'z-a': 't.name COLLATE NOCASE DESC',
        'newest': 't.created_at DESC',
        'oldest': 't.created_at ASC',
        'most': 'cnt DESC',
        'least': 'cnt ASC'
    }
    order = order_map.get(sort, 't.name COLLATE NOCASE ASC')
    conn = get_db()
    types = conn.execute(f"SELECT t.*, COUNT(e.id) as cnt FROM types t LEFT JOIN entries e ON t.id = e.type_id GROUP BY t.id ORDER BY {order}").fetchall()
    conn.close()
    return jsonify([{'id': t['id'], 'name': t['name'], 'count': t['cnt']} for t in types])

@app.route('/api/admin/types', methods=['POST'])
@csrf.exempt
@login_required
def api_admin_create_type():
    data = request.get_json()
    name = data.get('name', '').strip().lower()
    if not name:
        return jsonify({'error': 'Nama tipe diperlukan'}), 400
    conn = get_db()
    if conn.execute("SELECT id FROM types WHERE name=?", (name,)).fetchone():
        conn.close()
        return jsonify({'error': 'Tipe sudah ada'}), 409
    conn.execute("INSERT INTO types (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
    return jsonify({'success': True}), 201

@app.route('/api/admin/types/<int:id>', methods=['PUT'])
@csrf.exempt
@login_required
def api_admin_update_type(id):
    data = request.get_json()
    name = data.get('name', '').strip().lower()
    if not name:
        return jsonify({'error': 'Nama tipe diperlukan'}), 400
    conn = get_db()
    conn.execute("UPDATE types SET name=? WHERE id=?", (name, id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/types/<int:id>', methods=['DELETE'])
@csrf.exempt
@login_required
def api_admin_delete_type(id):
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) as cnt FROM entries WHERE type_id=?", (id,)).fetchone()['cnt']
    if cnt > 0:
        conn.close()
        return jsonify({'error': f'Tipe masih memiliki {cnt} entri'}), 409
    conn.execute("DELETE FROM types WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Sources ---
@app.route('/api/admin/sources')
@login_required
def api_admin_sources():
    sort = request.args.get('sort', 'a-z')
    order_map = {'a-z': 'source COLLATE NOCASE ASC', 'z-a': 'source COLLATE NOCASE DESC', 'most': 'cnt DESC', 'least': 'cnt ASC'}
    order = order_map.get(sort, 'source COLLATE NOCASE ASC')
    conn = get_db()
    sources = conn.execute(f"SELECT source, COUNT(*) as cnt FROM entries WHERE source != 'Anonim' AND source != '' GROUP BY source ORDER BY {order}").fetchall()
    conn.close()
    return jsonify([{'source': s['source'], 'count': s['cnt']} for s in sources])

# --- Tags ---
@app.route('/api/admin/tags')
@login_required
def api_admin_tags():
    sort = request.args.get('sort', 'a-z')
    conn = get_db()
    rows = conn.execute("SELECT tags FROM entries WHERE tags != ''").fetchall()
    conn.close()
    tag_counts = {}
    for r in rows:
        for t in parse_tags(r['tags']):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    items = list(tag_counts.items())
    if sort == 'z-a':
        items.sort(key=lambda x: x[0], reverse=True)
    elif sort == 'most':
        items.sort(key=lambda x: x[1], reverse=True)
    elif sort == 'least':
        items.sort(key=lambda x: x[1])
    else:
        items.sort(key=lambda x: x[0])
    return jsonify([{'tag': t, 'count': c} for t, c in items])

# --- Stats (Admin) ---
@app.route('/api/admin/stats')
@login_required
def api_admin_stats():
    conn = get_db()
    total_entries = conn.execute("SELECT COUNT(*) as cnt FROM entries").fetchone()['cnt']
    total_types = conn.execute("SELECT COUNT(*) as cnt FROM types").fetchone()['cnt']
    total_likes = conn.execute("SELECT SUM(like_count) as total FROM entries").fetchone()['total'] or 0
    conn.close()
    return jsonify({
        'total_entries': total_entries,
        'total_types': total_types,
        'total_likes': total_likes
    })

# --------------------------------------------------------------------
# Register Blueprint & Run
# --------------------------------------------------------------------
app.register_blueprint(admin_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)