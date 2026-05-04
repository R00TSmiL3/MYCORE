import os, time, sqlite3, logging
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

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
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

DATABASE = 'library.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    # Aktifkan WAL mode untuk performa dan menghindari lock saat inisialisasi
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
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
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by INTEGER,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES types (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users (id)
            );
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                visitor_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entry_id, visitor_id),
                FOREIGN KEY (entry_id) REFERENCES entries (id) ON DELETE CASCADE
            );
        ''')

        # Pastikan kolom like_count ada (upgrade)
        cols = [col[1] for col in conn.execute("PRAGMA table_info(entries)").fetchall()]
        if 'like_count' not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN like_count INTEGER DEFAULT 0")
            conn.commit()
            
        # Pastikan kolom role ada di tabel users (upgrade)
        cols_users = [col[1] for col in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'role' not in cols_users:
             conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
             conn.commit()
            
        # Tipe default
        if conn.execute("SELECT COUNT(*) FROM types").fetchone()[0] == 0:
            for t in ['puisi', 'quote', 'psikologi']:
                conn.execute("INSERT INTO types (name) VALUES (?)", (t,))

        # Admin default
        admin_user = os.getenv('ADMIN_USERNAME', 'admin')
        admin_pass = os.getenv('ADMIN_PASSWORD', 'admin123')
        if admin_pass == 'admin123' or app.config['SECRET_KEY'] == 'dev-secret-change-me':
            app.logger.warning("⚠️  Menggunakan kredensial default! Segera ubah melalui file .env")

        if not conn.execute("SELECT id FROM users WHERE username = ?", (admin_user,)).fetchone():
            conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                         (admin_user, generate_password_hash(admin_pass)))
            conn.commit()
    except sqlite3.OperationalError as e:
        app.logger.error(f"DB init error (mungkin race condition aman): {e}")
    finally:
        conn.close()

# Inisialisasi database di dalam app context (hanya sekali)
with app.app_context():
    init_db()

# --------------------------------------------------------------------
# Security utilities
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
    if is_ip_blocked(request.remote_addr):
        abort(403)

def is_safe_redirect_url(target):
    if not target:
        return False
    if '://' in target:
        return False
    if not target.startswith('/'):
        return False
    if any(c in target for c in '\r\n'):
        return False
    return True

# --------------------------------------------------------------------
# User model
# --------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, user_id, username, role='user'):
        self.id = user_id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        # Aman untuk sqlite3.Row: periksa apakah kolom 'role' ada
        role = row['role'] if 'role' in row.keys() else 'user'
        return User(row['id'], row['username'], role)
    return None

# --------------------------------------------------------------------
# Error handlers
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
def get_types_list():
    conn = get_db()
    types = conn.execute("SELECT * FROM types ORDER BY name").fetchall()
    conn.close()
    return [{'id': t['id'], 'name': t['name']} for t in types]

def parse_tags(tags_str):
    if not tags_str:
        return []
    return sorted(list(set(t.strip().lower() for t in tags_str.split(',') if t.strip())))

def allowed_length(value, max_len=5000):
    return len(value) <= max_len

# ====================================================================
# PUBLIC ROUTES
# ====================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logreg')
def logreg():
    return render_template('logreg.html')

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
    base = ("SELECT e.*, t.name as type_name, u.username "
            "FROM entries e "
            "JOIN types t ON e.type_id = t.id "
            "JOIN users u ON e.user_id = u.id")
    conds = ["e.status = 'passed'"]
    params = []
    if type_id and type_id.isdigit():
        conds.append("e.type_id = ?")
        params.append(int(type_id))
    if search:
        conds.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ? OR u.username LIKE ?)")
        params.extend([f"%{search}%"]*5)
    if source:
        conds.append("e.source LIKE ?")
        params.append(f"%{source}%")
    if tag:
        conds.append("e.tags LIKE ?")
        params.append(f"%{tag}%")
    ids_param = request.args.get('ids', '').strip()
    if ids_param:
        ids = [int(i) for i in ids_param.split(',') if i.isdigit()]
        if ids:
            placeholders = ','.join('?' * len(ids))
            conds.append(f"e.id IN ({placeholders})")
            params.extend(ids)

    where = "WHERE " + " AND ".join(conds) if conds else ""

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
    total = conn.execute(f"SELECT COUNT(*) as cnt FROM entries e JOIN types t ON e.type_id = t.id JOIN users u ON e.user_id = u.id {where}", params).fetchone()['cnt']

    liked_set = set()
    if visitor_id:
        entry_ids = [e['id'] for e in entries]
        if entry_ids:
            ph = ','.join('?'*len(entry_ids))
            liked_rows = conn.execute(
                f"SELECT entry_id FROM likes WHERE visitor_id = ? AND entry_id IN ({ph})",
                [visitor_id] + entry_ids).fetchall()
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
            'username': e['username'] if e['username'] else 'Anonim',
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
        return jsonify({'error': 'visitor_id tidak valid'}), 400

    conn = get_db()
    try:
        entry = conn.execute("SELECT id, status FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            return jsonify({'error': 'Entri tidak ditemukan'}), 404
        if entry['status'] != 'passed':
            return jsonify({'error': 'Entri belum disetujui'}), 403

        existing = conn.execute(
            "SELECT id FROM likes WHERE entry_id = ? AND visitor_id = ?",
            (entry_id, visitor_id)).fetchone()
        if existing:
            return jsonify({'error': 'Anda sudah menyukai entri ini'}), 409

        conn.execute("INSERT INTO likes (entry_id, visitor_id) VALUES (?, ?)", (entry_id, visitor_id))
        conn.execute("UPDATE entries SET like_count = like_count + 1 WHERE id = ?", (entry_id,))
        conn.commit()
        new_count = conn.execute("SELECT like_count FROM entries WHERE id = ?", (entry_id,)).fetchone()['like_count']
        return jsonify({'success': True, 'like_count': new_count})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Kesalahan database'}), 409
    except Exception as e:
        app.logger.error(f"Like error: {e}")
        return jsonify({'error': 'Kesalahan server'}), 500
    finally:
        conn.close()

@app.route('/api/entries/<int:entry_id>/like', methods=['DELETE'])
@csrf.exempt
@limiter.limit("30 per minute")
def unlike_entry(entry_id):
    data = request.get_json(silent=True) or {}
    visitor_id = data.get('visitor_id', '').strip()
    if not visitor_id or len(visitor_id) < 8:
        return jsonify({'error': 'visitor_id tidak valid'}), 400
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM likes WHERE entry_id = ? AND visitor_id = ?",
            (entry_id, visitor_id)).fetchone()
        if not existing:
            return jsonify({'error': 'Anda belum menyukai entri ini'}), 404
        conn.execute("DELETE FROM likes WHERE id = ?", (existing['id'],))
        conn.execute("UPDATE entries SET like_count = like_count - 1 WHERE id = ? AND like_count > 0", (entry_id,))
        conn.commit()
        new_count = conn.execute("SELECT like_count FROM entries WHERE id = ?", (entry_id,)).fetchone()['like_count']
        return jsonify({'success': True, 'like_count': new_count})
    except Exception as e:
        app.logger.error(f"Unlike error: {e}")
        return jsonify({'error': 'Kesalahan server'}), 500
    finally:
        conn.close()

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    types = conn.execute("SELECT t.id, t.name, COUNT(e.id) as cnt FROM types t LEFT JOIN entries e ON t.id = e.type_id AND e.status='passed' GROUP BY t.id ORDER BY t.name").fetchall()
    sources = conn.execute("SELECT source, COUNT(*) as cnt FROM entries WHERE source != 'Anonim' AND source != '' AND status='passed' GROUP BY source ORDER BY source").fetchall()
    tag_rows = conn.execute("SELECT tags FROM entries WHERE tags != '' AND status='passed'").fetchall()
    top_liked = conn.execute("SELECT id, content, like_count FROM entries WHERE status='passed' ORDER BY like_count DESC LIMIT 5").fetchall()
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

@app.route('/api/random')
def api_random():
    conn = get_db()
    entry = conn.execute("SELECT e.*, t.name as type_name, u.username FROM entries e JOIN types t ON e.type_id = t.id JOIN users u ON e.user_id = u.id WHERE e.status='passed' ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    if not entry:
        return jsonify({'error': 'Tidak ada entri'}), 404
    return jsonify({
        'id': entry['id'],
        'type': entry['type_name'],
        'type_id': entry['type_id'],
        'content': entry['content'],
        'source': entry['source'] or 'Anonim',
        'tags': parse_tags(entry['tags']),
        'like_count': entry['like_count'],
        'username': entry['username'],
        'created_at': entry['created_at']
    })

# ====================================================================
# USER AUTHENTICATION API
# ====================================================================
@app.route('/api/register', methods=['POST'])
@csrf.exempt
@limiter.limit("3 per minute")
def register():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    if not username or not password or len(username) < 3 or len(password) < 6:
        return jsonify({'error': 'Username min 3 karakter, password min 6 karakter.'}), 400
    if not username.isalnum():
        return jsonify({'error': 'Username hanya boleh huruf dan angka.'}), 400

    conn = get_db()
    if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        conn.close()
        return jsonify({'error': 'Username sudah digunakan.'}), 409

    try:
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'user')",
                     (username, generate_password_hash(password)))
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()['id']
        login_user(User(user_id, username, 'user'))
        conn.close()
        return jsonify({'success': True, 'username': username, 'role': 'user'}), 201
    except Exception as e:
        app.logger.error(f"Register error: {e}")
        return jsonify({'error': 'Gagal mendaftar.'}), 500
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
@csrf.exempt
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    conn = get_db()
    user_row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user_row and check_password_hash(user_row['password_hash'], password):
        role = user_row['role'] if 'role' in user_row.keys() else 'user'
        login_user(User(user_row['id'], user_row['username'], role))
        return jsonify({'success': True, 'username': username, 'role': role})
    return jsonify({'error': 'Username atau password salah.'}), 401

@app.route('/api/logout')
@login_required
def api_logout():
    logout_user()
    return jsonify({'success': True})

@app.route('/api/me')
@login_required
def api_me():
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'role': current_user.role
    })

# ====================================================================
# USER ENTRIES (CRUD by user)
# ====================================================================
@app.route('/api/entries', methods=['POST'])
@login_required
# @csrf.exempt  <-- CSRF protection diaktifkan kembali, token harus disertakan dari frontend
def api_create_entry():
    if current_user.role not in ('user', 'admin'):
        return jsonify({'error': 'Tidak diizinkan.'}), 403
    data = request.get_json()
    type_id = data.get('type_id')
    content = data.get('content', '').strip()
    source = data.get('source', '').strip() or 'Anonim'
    tags_raw = data.get('tags', '')
    if not type_id or not content:
        return jsonify({'error': 'Tipe dan konten wajib diisi.'}), 400
    if not allowed_length(content, 5000):
        return jsonify({'error': 'Konten terlalu panjang.'}), 400

    tags = ','.join(parse_tags(tags_raw))
    status = 'passed' if current_user.role == 'admin' else 'pending'
    conn = get_db()
    try:
        conn.execute("INSERT INTO entries (type_id, content, source, tags, user_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                     (int(type_id), content, source, tags, current_user.id, status))
        conn.commit()
        return jsonify({'success': True}), 201
    except Exception as e:
        app.logger.error(f"Create entry error: {e}")
        return jsonify({'error': 'Gagal menyimpan.'}), 500
    finally:
        conn.close()

@app.route('/api/my-entries')
@login_required
def api_my_entries():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    conn = get_db()
    entries = conn.execute(
        "SELECT e.*, t.name as type_name FROM entries e JOIN types t ON e.type_id = t.id WHERE e.user_id = ? ORDER BY e.created_at DESC LIMIT ? OFFSET ?",
        (current_user.id, per_page, offset)).fetchall()
    total = conn.execute("SELECT COUNT(*) as cnt FROM entries WHERE user_id = ?", (current_user.id,)).fetchone()['cnt']
    conn.close()
    result = []
    for e in entries:
        result.append({
            'id': e['id'],
            'type_name': e['type_name'],
            'content': e['content'],
            'source': e['source'],
            'tags': e['tags'],
            'status': e['status'],
            'like_count': e['like_count'],
            'created_at': e['created_at']
        })
    return jsonify({'entries': result, 'total': total, 'page': page, 'per_page': per_page})

# ====================================================================
# ADMIN BLUEPRINT & API
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
            role = user_row['role'] if 'role' in user_row.keys() else 'admin'
            if role != 'admin':
                flash('Hanya admin yang bisa mengakses halaman ini.', 'error')
                return render_template('admin/login.html')
            login_user(User(user_row['id'], user_row['username'], role))
            flash('Berhasil login.', 'success')
            next_page = request.args.get('next')
            if next_page and is_safe_redirect_url(next_page):
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
    if current_user.role != 'admin':
        abort(403)
    return render_template('admin/admin.html')

# --- Admin API endpoints ---
@app.route('/api/admin/entries', methods=['GET'])
@login_required
def api_admin_entries():
    if current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    status = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type', '').strip()  # <-- PERBAIKAN: menangkap filter type
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 20
    offset = (page-1)*per_page

    conn = get_db()
    base = ("SELECT e.*, t.name as type_name, u.username "
            "FROM entries e "
            "JOIN types t ON e.type_id = t.id "
            "JOIN users u ON e.user_id = u.id")
    conds = []
    params = []
    if status and status in ('pending','reviewed','passed','rejected'):
        conds.append("e.status = ?")
        params.append(status)
    if search:
        conds.append("(e.content LIKE ? OR e.source LIKE ? OR e.tags LIKE ? OR t.name LIKE ? OR u.username LIKE ?)")
        params.extend([f"%{search}%"]*5)
    if type_id and type_id.isdigit():
        conds.append("e.type_id = ?")
        params.append(int(type_id))
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = conn.execute(f"SELECT COUNT(*) as cnt FROM entries e JOIN types t ON e.type_id = t.id JOIN users u ON e.user_id = u.id {where}", params).fetchone()['cnt']
    entries = conn.execute(f"{base} {where} ORDER BY e.created_at DESC LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
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
            'username': e['username'],
            'status': e['status'],
            'rejection_reason': e['rejection_reason'] or '',
            'created_at': e['created_at']
        })
    return jsonify({'entries': result, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/admin/entries', methods=['POST'])
@login_required
def api_admin_create_entry():
    if current_user.role != 'admin':
        abort(403)
    data = request.get_json()
    if not data or not data.get('type_id') or not data.get('content'):
        return jsonify({'error': 'type_id dan content diperlukan'}), 400
    type_id = int(data['type_id'])
    content = data['content'].strip()
    if not allowed_length(content, 5000):
        return jsonify({'error': 'Konten terlalu panjang'}), 400
    source = data.get('source', '').strip() or 'Anonim'
    tags_raw = data.get('tags', '')
    tags = ','.join(parse_tags(tags_raw))

    conn = get_db()
    cur = conn.execute("INSERT INTO entries (type_id, content, source, tags, like_count, user_id, status) VALUES (?,?,?,?,0,?, 'passed')",
                       (type_id, content, source, tags, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': cur.lastrowid}), 201

@app.route('/api/admin/entries/<int:id>', methods=['GET'])
@login_required
def api_admin_get_entry(id):
    if current_user.role != 'admin':
        abort(403)
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
@login_required
def api_admin_update_entry(id):
    if current_user.role != 'admin':
        abort(403)
    data = request.get_json()
    if not data or not data.get('type_id') or not data.get('content'):
        return jsonify({'error': 'type_id dan content diperlukan'}), 400
    content = data['content'].strip()
    if not allowed_length(content, 5000):
        return jsonify({'error': 'Konten terlalu panjang'}), 400
    type_id = int(data['type_id'])
    source = data.get('source', '').strip() or 'Anonim'
    tags = ','.join(parse_tags(data.get('tags', '')))

    conn = get_db()
    conn.execute("UPDATE entries SET type_id=?, content=?, source=?, tags=? WHERE id=?",
                 (type_id, content, source, tags, id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/entries/<int:id>', methods=['DELETE'])
@login_required
def api_admin_delete_entry(id):
    if current_user.role != 'admin':
        abort(403)
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/entries/<int:id>/review', methods=['PUT'])
@csrf.exempt
@login_required
def review_entry(id):
    if current_user.role != 'admin':
        abort(403)
    data = request.get_json()
    action = data.get('action')  # 'passed' or 'rejected'
    reason = data.get('reason', '').strip()
    if action not in ('passed', 'rejected'):
        return jsonify({'error': 'Aksi tidak valid.'}), 400
    conn = get_db()
    entry = conn.execute("SELECT * FROM entries WHERE id = ?", (id,)).fetchone()
    if not entry:
        conn.close()
        return jsonify({'error': 'Entri tidak ditemukan.'}), 404
    new_status = 'passed' if action == 'passed' else 'rejected'
    conn.execute("UPDATE entries SET status = ?, reviewed_by = ?, rejection_reason = ? WHERE id = ?",
                 (new_status, current_user.id, reason if action == 'rejected' else None, id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Types (admin only) ---
@app.route('/api/admin/types', methods=['GET'])
@login_required
def api_admin_types():
    if current_user.role != 'admin':
        abort(403)
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
@login_required
def api_admin_create_type():
    if current_user.role != 'admin':
        abort(403)
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
@login_required
def api_admin_update_type(id):
    if current_user.role != 'admin':
        abort(403)
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
@login_required
def api_admin_delete_type(id):
    if current_user.role != 'admin':
        abort(403)
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) as cnt FROM entries WHERE type_id=?", (id,)).fetchone()['cnt']
    if cnt > 0:
        conn.close()
        return jsonify({'error': f'Tipe masih memiliki {cnt} entri'}), 409
    conn.execute("DELETE FROM types WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Sources (admin) ---
@app.route('/api/admin/sources')
@login_required
def api_admin_sources():
    if current_user.role != 'admin':
        abort(403)
    sort = request.args.get('sort', 'a-z')
    order_map = {'a-z': 'source COLLATE NOCASE ASC', 'z-a': 'source COLLATE NOCASE DESC', 'most': 'cnt DESC', 'least': 'cnt ASC'}
    order = order_map.get(sort, 'source COLLATE NOCASE ASC')
    conn = get_db()
    sources = conn.execute(f"SELECT source, COUNT(*) as cnt FROM entries WHERE source != 'Anonim' AND source != '' GROUP BY source ORDER BY {order}").fetchall()
    conn.close()
    return jsonify([{'source': s['source'], 'count': s['cnt']} for s in sources])

# --- Tags (admin) ---
@app.route('/api/admin/tags')
@login_required
def api_admin_tags():
    if current_user.role != 'admin':
        abort(403)
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

# --- Stats (admin) ---
@app.route('/api/admin/stats')
@login_required
def api_admin_stats():
    if current_user.role != 'admin':
        abort(403)
    conn = get_db()
    total_entries = conn.execute("SELECT COUNT(*) as cnt FROM entries").fetchone()['cnt']
    total_types = conn.execute("SELECT COUNT(*) as cnt FROM types").fetchone()['cnt']
    total_likes = conn.execute("SELECT SUM(like_count) as total FROM entries").fetchone()['total'] or 0
    conn.close()
    return jsonify({'total_entries': total_entries, 'total_types': total_types, 'total_likes': total_likes})

app.register_blueprint(admin_bp)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)