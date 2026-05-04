// logreg.js – Handle login dan register di logreg.html
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

async function apiFetch(url, options = {}) {
    if (!options.method || ['POST', 'PUT', 'DELETE'].includes(options.method.toUpperCase())) {
        options.headers = options.headers || {};
        options.headers['X-CSRFToken'] = csrfToken;
    }
    const res = await fetch(url, options);
    return res;
}

const formContainer = document.getElementById('formContainer');
let currentMode = 'login'; // 'login' atau 'register'

function renderForm() {
    const isLogin = currentMode === 'login';
    formContainer.innerHTML = `
        <div id="flashArea"></div>
        <div class="form-group">
            <label for="username">Username</label>
            <input type="text" id="username" class="form-control" placeholder="Username" required autocomplete="username">
        </div>
        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" class="form-control" placeholder="Password" required autocomplete="current-password">
        </div>
        <button class="btn" id="submitBtn">${isLogin ? 'Masuk' : 'Daftar'}</button>
        <p style="margin-top:1rem;">
            <span class="switch-link" id="switchMode">
                ${isLogin ? 'Belum punya akun? Daftar' : 'Sudah punya akun? Masuk'}
            </span>
        </p>
    `;

    document.getElementById('switchMode').addEventListener('click', () => {
        currentMode = isLogin ? 'register' : 'login';
        renderForm();
    });

    document.getElementById('submitBtn').addEventListener('click', handleSubmit);
}

function showFlash(msg, type) {
    const flashArea = document.getElementById('flashArea');
    flashArea.innerHTML = `<div class="flash-msg ${type}">${msg}</div>`;
}

async function handleSubmit() {
    const username = document.getElementById('username').value.trim().toLowerCase();
    const password = document.getElementById('password').value;

    if (!username || !password) {
        showFlash('Username dan password harus diisi.', 'error');
        return;
    }
    if (currentMode === 'register' && password.length < 6) {
        showFlash('Password minimal 6 karakter.', 'error');
        return;
    }
    if (currentMode === 'register' && !/^[a-z0-9]+$/.test(username)) {
        showFlash('Username hanya boleh huruf dan angka.', 'error');
        return;
    }

    const url = currentMode === 'login' ? '/api/login' : '/api/register';
    try {
        const res = await apiFetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (res.ok) {
            showFlash(currentMode === 'login' ? 'Berhasil masuk.' : 'Akun berhasil dibuat.', 'success');
            // Redirect ke halaman utama setelah 1 detik
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showFlash(data.error || 'Terjadi kesalahan.', 'error');
        }
    } catch {
        showFlash('Tidak dapat terhubung ke server.', 'error');
    }
}

// Inisialisasi
renderForm();