"""
app.py – Flask application untuk Perpustakaan Kata
Menyediakan:
- API publik untuk showcase
- Admin panel (login, CRUD entries)
- Keamanan: bcrypt, CSRF, rate limiting, session protection
"""

import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify, Blueprint)
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# Memuat variabel dari .env
load_dotenv()

# --------------------------------------------------------------------
# Konfigurasi Aplikasi
# --------------------------------------------------------------------
app = Flask(__name__)

# Secret key untuk session dan CSRF (gunakan nilai acak panjang di production)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-change-me')
app.config['WTF_CSRF_ENABLED'] = True
# Agar token CSRF hanya dikirim melalui header/cookie, bukan parameter URL (default aman)
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 jam

# Session security
app.config['SESSION_COOKIE_HTTPONLY'] = True   # Mencegah akses cookie via JavaScript
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Lindungi dari CSRF
# Di production dengan HTTPS, aktifkan:
# app.config['SESSION_COOKIE_SECURE'] = True

# Inisialisasi plugin
csrf = CSRFProtect(app)  # Otomatis proteksi semua form yang mengandung csrf_token
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = 'admin.login'  # rute login untuk redirect
login_manager.session_protection = "strong"  # Invalidasi session jika IP/user-agent berubah
login_manager.init_app(app)

# --------------------------------------------------------------------
# Database Helper
# --------------------------------------------------------------------
DATABASE = 'library.db'

def get_db():
    """Mendapatkan koneksi database dengan row factory."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Memungkinkan akses kolom via nama
    return conn

def init_db():
    """Membuat tabel users dan entries jika belum ada.
       Juga membuat admin default dari .env jika tidak ada user."""
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('puisi','quote','psikologi')),
            content TEXT NOT NULL,
            source TEXT DEFAULT 'Anonim',
            tags TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Admin default (ganti password via .env)
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    existing = conn.execute("SELECT id FROM users WHERE username = ?",
                            (admin_username,)).fetchone()
    if not existing:
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')  # Ganti!
        password_hash = generate_password_hash(admin_password)
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (admin_username, password_hash))
        print(f"Admin user '{admin_username}' created.")
    conn.commit()
    conn.close()

# Jalankan inisialisasi database sebelum request pertama
with app.app_context():
    init_db()

# --------------------------------------------------------------------
# User Class (Flask-Login)
# --------------------------------------------------------------------
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    """Load user dari database berdasarkan user_id (session)."""
    conn = get_db()
    user_row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user_row:
        return User(user_row['id'], user_row['username'])
    return None

# --------------------------------------------------------------------
# Error Handlers (Keamanan: jangan bocorkan detail error)
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

# --------------------------------------------------------------------
# ROUTE PUBLIK: Showcase (Frontend)
# --------------------------------------------------------------------
@app.route('/')
def index():
    """Halaman utama showcase. Data diambil via API."""
    return render_template('index.html')

# --------------------------------------------------------------------
# API Publik untuk Showcase
# --------------------------------------------------------------------
@app.route('/api/entries')
def api_entries():
    """
    Endpoint API untuk mendapatkan entries dengan filter/search/pagination.
    Parameter query:
        search (str) : cari di content, source, tags
        type (str)   : 'puisi','quote','psikologi', atau 'all' (default)
        tag (str)    : filter by tag (substring match pada kolom tags)
        page (int)   : halaman (default 1)
        per_page (int): jumlah per halaman (default 15)
    """
    search = request.args.get('search', '').lower().strip()
    type_filter = request.args.get('type', 'all').lower()
    tag_filter = request.args.get('tag', '').lower().strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    # Validasi per_page agar tidak terlalu besar
    per_page = min(per_page, 50)

    offset = (page - 1) * per_page

    conn = get_db()
    # Bangun kondisi WHERE dengan parameterized query (mencegah SQL injection)
    conditions = []
    params = []

    if type_filter and type_filter != 'all':
        if type_filter in ('puisi', 'quote', 'psikologi'):
            conditions.append("type = ?")
            params.append(type_filter)
        else:
            return jsonify({"error": "Invalid type"}), 400

    if search:
        conditions.append("(content LIKE ? OR source LIKE ? OR tags LIKE ?)")
        like_search = f"%{search}%"
        params.extend([like_search, like_search, like_search])

    if tag_filter:
        conditions.append("tags LIKE ?")
        params.append(f"%{tag_filter}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Query data dengan LIMIT & OFFSET
    query = f"SELECT * FROM entries {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    query_params = params + [per_page, offset]
    entries = conn.execute(query, query_params).fetchall()

    # Hitung total entries tanpa LIMIT
    count_query = f"SELECT COUNT(*) as total FROM entries {where_clause}"
    total_row = conn.execute(count_query, params).fetchone()
    total = total_row['total'] if total_row else 0

    conn.close()

    # Format data untuk JSON
    result = []
    for entry in entries:
        tags_list = entry['tags'].split(',') if entry['tags'] else []
        tags_list = [tag.strip() for tag in tags_list if tag.strip()]  # bersihkan
        result.append({
            'id': entry['id'],
            'type': entry['type'],
            'content': entry['content'],
            'source': entry['source'] or 'Anonim',
            'tags': tags_list
        })

    return jsonify({
        'entries': result,
        'page': page,
        'per_page': per_page,
        'total': total
    })

# --------------------------------------------------------------------
# ADMIN BLUEPRINT
# --------------------------------------------------------------------
admin_bp = Blueprint('admin', __name__, url_prefix='/admin',
                     template_folder='templates/admin')

# Decorator untuk membutuhkan login di setiap route admin
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function

# --------------------------------------------------------------------
# Admin - Login
# --------------------------------------------------------------------
@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Rate limiting untuk mencegah brute force
def login():
    """Halaman login admin."""
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Username dan password harus diisi.', 'error')
            return render_template('admin/login.html')

        conn = get_db()
        user_row = conn.execute("SELECT * FROM users WHERE username = ?",
                                (username,)).fetchone()
        conn.close()

        if user_row and check_password_hash(user_row['password_hash'], password):
            user_obj = User(user_row['id'], user_row['username'])
            login_user(user_obj)
            flash('Berhasil login.', 'success')
            next_page = request.args.get('next')
            # Pastikan redirect hanya ke dalam aplikasi (hindari open redirect)
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Username atau password salah.', 'error')

    return render_template('admin/login.html')

# --------------------------------------------------------------------
# Admin - Logout
# --------------------------------------------------------------------
@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('admin.login'))

# --------------------------------------------------------------------
# Admin - Dashboard (daftar entries)
# --------------------------------------------------------------------
@admin_bp.route('/')
@admin_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as count FROM entries").fetchone()['count']
    entries = conn.execute(
        "SELECT * FROM entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    ).fetchall()
    conn.close()

    return render_template('admin/dashboard.html',
                           entries=entries,
                           page=page,
                           total=total,
                           per_page=per_page)

# --------------------------------------------------------------------
# Admin - Tambah Entry
# --------------------------------------------------------------------
@admin_bp.route('/add', methods=['GET', 'POST'])
@admin_required
def add_entry():
    """Form untuk menambah entry baru."""
    if request.method == 'POST':
        type_ = request.form.get('type', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip() or 'Anonim'
        tags_raw = request.form.get('tags', '')

        # Validasi server-side
        if not type_ or type_ not in ('puisi', 'quote', 'psikologi'):
            flash('Tipe entri tidak valid.', 'error')
            return render_template('admin/edit.html', entry=None)
        if not content:
            flash('Konten tidak boleh kosong.', 'error')
            return render_template('admin/edit.html', entry=None)

        # Bersihkan dan proses tags
        if tags_raw:
            tags_list = [t.strip().lower() for t in tags_raw.split(',') if t.strip()]
            tags_str = ','.join(tags_list)
        else:
            tags_str = ''

        conn = get_db()
        conn.execute(
            "INSERT INTO entries (type, content, source, tags) VALUES (?, ?, ?, ?)",
            (type_, content, source, tags_str)
        )
        conn.commit()
        conn.close()
        flash('Entri berhasil ditambahkan.', 'success')
        return redirect(url_for('admin.dashboard'))
    # GET request
    return render_template('admin/edit.html', entry=None)

# --------------------------------------------------------------------
# Admin - Edit Entry
# --------------------------------------------------------------------
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
        type_ = request.form.get('type', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip() or 'Anonim'
        tags_raw = request.form.get('tags', '')

        if not type_ or type_ not in ('puisi', 'quote', 'psikologi'):
            flash('Tipe entri tidak valid.', 'error')
            conn.close()
            return render_template('admin/edit.html', entry=entry)
        if not content:
            flash('Konten tidak boleh kosong.', 'error')
            conn.close()
            return render_template('admin/edit.html', entry=entry)

        if tags_raw:
            tags_list = [t.strip().lower() for t in tags_raw.split(',') if t.strip()]
            tags_str = ','.join(tags_list)
        else:
            tags_str = ''

        conn.execute(
            "UPDATE entries SET type=?, content=?, source=?, tags=? WHERE id=?",
            (type_, content, source, tags_str, id)
        )
        conn.commit()
        conn.close()
        flash('Entri berhasil diperbarui.', 'success')
        return redirect(url_for('admin.dashboard'))

    conn.close()
    return render_template('admin/edit.html', entry=entry)

# --------------------------------------------------------------------
# Admin - Hapus Entry
# --------------------------------------------------------------------
@admin_bp.route('/delete/<int:id>', methods=['POST'])
@admin_required
def delete_entry(id):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Entri dihapus.', 'info')
    return redirect(url_for('admin.dashboard'))

# Daftarkan blueprint
app.register_blueprint(admin_bp)

# --------------------------------------------------------------------
# Jalankan Aplikasi
# --------------------------------------------------------------------
if __name__ == '__main__':
    # Development server – jangan digunakan di production!
    app.run(host='0.0.0.0', port=5000, debug=False)