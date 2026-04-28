arsip-rasa/                      # Root proyek
│
├── .env                         # Variabel lingkungan (SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD)
├── .gitignore                   # Abaikan .env, library.db, __pycache__, dll.
├── app.py                       # Aplikasi utama Flask (routes publik + admin)
├── requirements.txt             # Dependensi Python
├── library.db                   # Database SQLite (dibuat otomatis saat runtime)
│
├── static/                      # Aset statis publik (CSS, JS, gambar, dll.)
│   ├── css/
│   │   └── style.css            # Gaya untuk showcase utama
│   └── js/
│       └── script.js            # Fetch API, infinite scroll, filter untuk showcase
│
└── templates/                   # Template Jinja2
    ├── index.html               # Halaman showcase publik (grid kutipan/puisi)
    ├── 404.html                 # Halaman error 404 (opsional)
    ├── 500.html                 # Halaman error 500 (opsional)
    └── admin/                   # Template khusus admin panel
        ├── base.html            # Layout dasar admin (navbar, flash messages)
        ├── login.html           # Form login admin
        ├── dashboard.html       # Daftar semua entri (tabel + pagination)
        └── edit.html           # Form tambah/edit entri