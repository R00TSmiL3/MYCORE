// admin.js – SPA Admin Panel with CSRF and HTML escaping

// CSRF token from meta tag
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

function apiFetch(url, options = {}) {
  if (!options.headers) options.headers = {};
  options.headers['X-CSRFToken'] = csrfToken;
  return fetch(url, options);
}

// --- HTML escape function (prevents XSS) ---
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const API_ENTRIES = '/api/admin/entries';
const API_TYPES = '/api/admin/types';
const API_SOURCES = '/api/admin/sources';
const API_TAGS = '/api/admin/tags';
const API_STATS = '/api/admin/stats';

let currentPage = 'dashboard';
let entriesPage = 1, entriesTotal = 0;
let entrySearch = '', entryFilterType = '', entrySort = 'newest';

// Navigation
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    switchPage(link.dataset.page);
  });
});

function switchPage(page) {
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  document.querySelector(`.nav-link[data-page="${page}"]`).classList.add('active');
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');
  currentPage = page;
  if (page === 'dashboard') loadDashboard();
  else if (page === 'entries') loadEntries();
  else if (page === 'types') loadTypes();
  else if (page === 'sources') loadSources();
  else if (page === 'tags') loadTags();
}

// Flash message
function showFlash(msg, type = 'info') {
  const flash = document.createElement('div');
  flash.className = `flash-msg ${type}`;
  flash.textContent = msg; // safe, no HTML
  document.querySelector('.main-content').prepend(flash);
  setTimeout(() => flash.remove(), 4000);
}

// Modal helpers
function openModal(html) {
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal').classList.add('active');
}
function closeModal() {
  document.getElementById('modal').classList.remove('active');
}
document.querySelector('.modal-close').addEventListener('click', closeModal);
window.addEventListener('click', e => {
  if (e.target === document.getElementById('modal')) closeModal();
});

// Dashboard
async function loadDashboard() {
  try {
    const statsRes = await apiFetch(API_STATS);
    const stats = await statsRes.json();
    document.getElementById('stat-entries').textContent = stats.total_entries;
    document.getElementById('stat-types').textContent = stats.total_types;
    document.getElementById('stat-likes').textContent = stats.total_likes;

    const entriesRes = await apiFetch(`${API_ENTRIES}?per_page=5&sort=newest`);
    const data = await entriesRes.json();
    let html = '';
    if (data.entries.length) {
      html = `
        <table>
          <thead><tr><th>ID</th><th>Tipe</th><th>Konten</th><th>Sumber</th><th>Likes</th></tr></thead>
          <tbody>
            ${data.entries.map(e => `
              <tr>
                <td>${e.id}</td>
                <td>${escapeHtml(e.type_name)}</td>
                <td>${escapeHtml(e.content.substring(0,60))}...</td>
                <td>${escapeHtml(e.source)}</td>
                <td>${e.like_count}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>`;
    } else {
      html = '<p>Belum ada entri.</p>';
    }
    document.getElementById('recent-entries').innerHTML = html;
  } catch (err) {
    console.error(err);
    showFlash('Gagal memuat dashboard.', 'error');
  }
}

// Entries
async function loadEntries() {
  entrySearch = document.getElementById('entry-search').value.trim();
  entryFilterType = document.getElementById('entry-type-filter').value;
  entrySort = document.getElementById('entry-sort').value;
  const params = new URLSearchParams({ page: entriesPage, per_page: 20, sort: entrySort, search: entrySearch, type: entryFilterType });
  try {
    const res = await apiFetch(`${API_ENTRIES}?${params}`);
    const data = await res.json();
    entriesTotal = data.total;
    let html = '';
    if (data.entries.length) {
      html = `
        <table>
          <thead><tr><th>ID</th><th>Tipe</th><th>Konten</th><th>Sumber</th><th>Tag</th><th>Likes</th><th>Aksi</th></tr></thead>
          <tbody>
            ${data.entries.map(e => `
              <tr>
                <td>${e.id}</td>
                <td>${escapeHtml(e.type_name)}</td>
                <td>${escapeHtml(e.content.substring(0,60))}...</td>
                <td>${escapeHtml(e.source)}</td>
                <td>${escapeHtml(e.tags)}</td>
                <td>${e.like_count}</td>
                <td>
                  <button class="btn btn-sm edit-entry" data-id="${e.id}">Edit</button>
                  <button class="btn btn-sm btn-danger delete-entry" data-id="${e.id}">Hapus</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>`;
    } else {
      html = '<p>Tidak ada entri.</p>';
    }
    document.getElementById('entries-table').innerHTML = html;
    renderEntriesPagination();
    attachEntryEvents();
  } catch (err) {
    console.error(err);
    showFlash('Gagal memuat entri.', 'error');
  }
}

function renderEntriesPagination() {
  const totalPages = Math.ceil(entriesTotal / 20);
  let html = '';
  if (entriesPage > 1) html += `<a href="#" data-page="${entriesPage-1}">←</a>`;
  html += `<span>Hal ${entriesPage} / ${totalPages}</span>`;
  if (entriesPage < totalPages) html += `<a href="#" data-page="${entriesPage+1}">→</a>`;
  document.getElementById('entries-pagination').innerHTML = html;
  document.querySelectorAll('#entries-pagination a').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      entriesPage = parseInt(a.dataset.page);
      loadEntries();
    });
  });
}

function attachEntryEvents() {
  document.querySelectorAll('.edit-entry').forEach(btn => btn.addEventListener('click', () => showEntryModal(btn.dataset.id)));
  document.querySelectorAll('.delete-entry').forEach(btn => btn.addEventListener('click', () => deleteEntry(btn.dataset.id)));
}

async function showEntryModal(id = null) {
  const typesRes = await apiFetch(API_TYPES);
  const types = await typesRes.json();
  let entry = { type_id: '', content: '', source: '', tags: '' };
  if (id) {
    const res = await apiFetch(`${API_ENTRIES}/${id}`);
    if (res.ok) entry = await res.json();
    else return showFlash('Entri tidak ditemukan.', 'error');
  }
  // Note: Values inserted into input/textarea are safe without escaping,
  // but if we ever embed in HTML context we must escape.
  openModal(`
    <h3>${id ? 'Edit Entri' : 'Tambah Entri'}</h3>
    <div style="display:flex;flex-direction:column;gap:1rem;margin-top:1rem;">
      <select id="modal-type" class="form-control">${types.map(t => `<option value="${t.id}" ${t.id==entry.type_id?'selected':''}>${escapeHtml(t.name)}</option>`).join('')}</select>
      <textarea id="modal-content" class="form-control" rows="5">${escapeHtml(entry.content)}</textarea>
      <input type="text" id="modal-source" class="form-control" value="${escapeHtml(entry.source)}" placeholder="Sumber">
      <input type="text" id="modal-tags" class="form-control" value="${escapeHtml(entry.tags)}" placeholder="Tag (pisahkan koma)">
      <button class="btn" id="save-entry">Simpan</button>
    </div>
  `);
  document.getElementById('save-entry').addEventListener('click', async () => {
    const data = {
      type_id: document.getElementById('modal-type').value,
      content: document.getElementById('modal-content').value,
      source: document.getElementById('modal-source').value,
      tags: document.getElementById('modal-tags').value
    };
    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API_ENTRIES}/${id}` : API_ENTRIES;
    const res = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (res.ok) {
      closeModal();
      loadEntries();
      showFlash(id ? 'Entri diperbarui.' : 'Entri ditambahkan.', 'success');
    } else {
      const err = await res.json();
      showFlash(err.error || 'Gagal menyimpan.', 'error');
    }
  });
}

async function deleteEntry(id) {
  if (!confirm('Hapus entri ini?')) return;
  const res = await apiFetch(`${API_ENTRIES}/${id}`, { method: 'DELETE' });
  if (res.ok) {
    loadEntries();
    showFlash('Entri dihapus.', 'info');
  }
}

// Types
async function loadTypes() {
  const sort = document.getElementById('type-sort').value;
  const res = await apiFetch(`${API_TYPES}?sort=${sort}`);
  const types = await res.json();
  let html = '';
  if (types.length) {
    html = `
      <table>
        <thead><tr><th>ID</th><th>Nama</th><th>Jumlah</th><th>Aksi</th></tr></thead>
        <tbody>
          ${types.map(t => `
            <tr>
              <td>${t.id}</td>
              <td>${escapeHtml(t.name)}</td>
              <td>${t.count}</td>
              <td>
                <button class="btn btn-sm edit-type" data-id="${t.id}" data-name="${escapeHtml(t.name)}">Edit</button>
                <button class="btn btn-sm btn-danger delete-type" data-id="${t.id}">Hapus</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;
  } else {
    html = '<p>Belum ada tipe.</p>';
  }
  document.getElementById('types-table').innerHTML = html;
  attachTypeEvents();
}

function attachTypeEvents() {
  document.querySelectorAll('.edit-type').forEach(btn => {
    btn.addEventListener('click', () => showTypeModal(btn.dataset.id, btn.dataset.name));
  });
  document.querySelectorAll('.delete-type').forEach(btn => {
    btn.addEventListener('click', () => deleteType(btn.dataset.id));
  });
}

function showTypeModal(id = null, name = '') {
  openModal(`
    <h3>${id ? 'Edit Tipe' : 'Tambah Tipe'}</h3>
    <div style="display:flex;flex-direction:column;gap:1rem;margin-top:1rem;">
      <input type="text" id="modal-type-name" class="form-control" value="${escapeHtml(name)}" placeholder="Nama tipe">
      <button class="btn" id="save-type">Simpan</button>
    </div>
  `);
  document.getElementById('save-type').addEventListener('click', async () => {
    const newName = document.getElementById('modal-type-name').value.trim();
    if (!newName) return showFlash('Nama tipe diperlukan.', 'error');
    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API_TYPES}/${id}` : API_TYPES;
    const res = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName })
    });
    if (res.ok) {
      closeModal();
      loadTypes();
      showFlash(id ? 'Tipe diperbarui.' : 'Tipe ditambahkan.', 'success');
    } else {
      const err = await res.json();
      showFlash(err.error || 'Gagal menyimpan.', 'error');
    }
  });
}

async function deleteType(id) {
  if (!confirm('Hapus tipe ini?')) return;
  const res = await apiFetch(`${API_TYPES}/${id}`, { method: 'DELETE' });
  if (res.ok) {
    loadTypes();
    showFlash('Tipe dihapus.', 'info');
  } else {
    const err = await res.json();
    showFlash(err.error, 'error');
  }
}

// Sources
async function loadSources() {
  const sort = document.getElementById('source-sort').value;
  const res = await apiFetch(`${API_SOURCES}?sort=${sort}`);
  const sources = await res.json();
  let html = '';
  if (sources.length) {
    html = `
      <table>
        <thead><tr><th>Sumber</th><th>Jumlah</th></tr></thead>
        <tbody>
          ${sources.map(s => `<tr><td>${escapeHtml(s.source)}</td><td>${s.count}</td></tr>`).join('')}
        </tbody>
      </table>`;
  } else {
    html = '<p>Tidak ada sumber.</p>';
  }
  document.getElementById('sources-table').innerHTML = html;
}

// Tags
async function loadTags() {
  const sort = document.getElementById('tag-sort').value;
  const res = await apiFetch(`${API_TAGS}?sort=${sort}`);
  const tags = await res.json();
  let html = '';
  if (tags.length) {
    html = `
      <table>
        <thead><tr><th>Tag</th><th>Jumlah</th></tr></thead>
        <tbody>
          ${tags.map(t => `<tr><td>#${escapeHtml(t.tag)}</td><td>${t.count}</td></tr>`).join('')}
        </tbody>
      </table>`;
  } else {
    html = '<p>Tidak ada tag.</p>';
  }
  document.getElementById('tags-table').innerHTML = html;
}

// Event listeners for toolbar elements
document.getElementById('entry-search').addEventListener('input', () => { entriesPage=1; loadEntries(); });
document.getElementById('entry-type-filter').addEventListener('change', () => { entriesPage=1; loadEntries(); });
document.getElementById('entry-sort').addEventListener('change', () => { entriesPage=1; loadEntries(); });
document.getElementById('btn-add-entry').addEventListener('click', () => showEntryModal());
document.getElementById('type-sort').addEventListener('change', loadTypes);
document.getElementById('btn-add-type').addEventListener('click', () => showTypeModal());
document.getElementById('source-sort').addEventListener('change', loadSources);
document.getElementById('tag-sort').addEventListener('change', loadTags);

// Initial load of type filter options
(async function init() {
  try {
    const res = await apiFetch(API_TYPES);
    const types = await res.json();
    const select = document.getElementById('entry-type-filter');
    select.innerHTML = '<option value="">Semua Tipe</option>';
    types.forEach(t => {
      select.innerHTML += `<option value="${t.id}">${escapeHtml(t.name)} (${t.count})</option>`;
    });
  } catch(err) { console.error(err); }
  switchPage('dashboard');
})();