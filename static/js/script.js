const API_ENTRIES = '/api/entries';
const API_STATS   = '/api/stats';
const BATCH_SIZE  = 15;

let currentType   = '';
let currentSource = '';
let currentTag    = '';
let currentSearch = '';
let currentSort   = 'newest';
let currentPage   = 1;
let currentTotal  = 0;
let isLoading     = false;

const grid = document.getElementById('cardGrid');
const loader = document.getElementById('loader');
const searchInput = document.getElementById('searchInput');
const typeSelect = document.getElementById('typeSelect');
const sourceInput = document.getElementById('sourceInput');
const tagInput = document.getElementById('tagInput');
const sortSelect = document.getElementById('sortSelect');
const statsContainer = document.getElementById('statsContainer');

function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderCards(entries) {
  entries.forEach(entry => {
    const card = document.createElement('div');
    card.className = 'card';
    const typeClass = `type-${entry.type.toLowerCase().replace(/[^a-z]/g, '')}`;
    card.innerHTML = `
      <span class="type-badge ${typeClass}">${entry.type.toUpperCase()}</span>
      <div class="content">${escapeHTML(entry.content)}</div>
      <div class="footer">
        <span class="source">— ${escapeHTML(entry.source)}</span>
        <div class="tags">
          ${entry.tags.map(tag => `<span class="tag">#${escapeHTML(tag)}</span>`).join('')}
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
}

async function fetchEntries(reset = false) {
  if (reset) { currentPage = 1; grid.innerHTML = ''; }
  const params = new URLSearchParams();
  params.set('page', currentPage);
  params.set('per_page', BATCH_SIZE);
  if (currentSearch) params.set('search', currentSearch);
  if (currentType) params.set('type', currentType);
  if (currentSource) params.set('source', currentSource);
  if (currentTag) params.set('tag', currentTag);
  params.set('sort', currentSort);
  try {
    const res = await fetch(`${API_ENTRIES}?${params}`);
    if (!res.ok) throw new Error('Gagal memuat data');
    const data = await res.json();
    currentTotal = data.total;
    renderCards(data.entries);
    loader.style.display = (currentPage * BATCH_SIZE < currentTotal) ? 'block' : 'none';
  } catch (err) {
    console.error(err);
    loader.textContent = 'Gagal memuat.';
    loader.style.display = 'block';
  }
}

window.addEventListener('scroll', () => {
  if (isLoading || currentPage * BATCH_SIZE >= currentTotal) return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 200) {
    isLoading = true;
    currentPage++;
    fetchEntries().finally(() => isLoading = false);
  }
});

function updateFilters() {
  currentSearch = searchInput.value.trim();
  currentType = typeSelect.value;
  currentSource = sourceInput.value.trim();
  currentTag = tagInput.value.trim();
  currentSort = sortSelect.value;
  fetchEntries(true);
}

function debounce(fn, delay) {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

searchInput.addEventListener('input', debounce(updateFilters, 300));
typeSelect.addEventListener('change', updateFilters);
sourceInput.addEventListener('input', debounce(updateFilters, 300));
tagInput.addEventListener('input', debounce(updateFilters, 300));
sortSelect.addEventListener('change', updateFilters);

async function loadStatsAndTypes() {
  try {
    const res = await fetch(API_STATS);
    const stats = await res.json();
    // Populate type dropdown
    typeSelect.innerHTML = '<option value="">Semua Tipe</option>';
    stats.types.forEach(t => {
      typeSelect.innerHTML += `<option value="${t.id}">${t.name} (${t.count})</option>`;
    });
    // Tampilkan statistik ringkas
    if (statsContainer) {
      let html = '<div style="display:flex; gap:2rem; flex-wrap:wrap; justify-content:center;">';
      html += '<div><strong>Tipe:</strong> ' + stats.types.map(t => `${t.name} (${t.count})`).join(', ') + '</div>';
      html += '<div><strong>Sumber Teratas:</strong> ' + stats.sources.slice(0,5).map(s => `${s.source} (${s.count})`).join(', ') + '</div>';
      html += '<div><strong>Tag Populer:</strong> ' + stats.tags.slice(0,8).map(t => `#${t.tag} (${t.count})`).join(', ') + '</div>';
      html += '</div>';
      statsContainer.innerHTML = html;
    }
  } catch (err) {
    console.error('Gagal memuat statistik:', err);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadStatsAndTypes();
  fetchEntries(true);
});