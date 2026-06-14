// ===== Auth =====
async function checkAuth() {
  const loginScreen = document.getElementById("loginScreen");
  if (localStorage.getItem("resident_auth") === "1") {
    loginScreen.style.display = "none";
    return;
  }
  loginScreen.style.display = "flex";
}

document.getElementById("loginBtn").addEventListener("click", async () => {
  const pass = document.getElementById("residentPass").value;
  const err = document.getElementById("loginError");
  if (!pass) { err.textContent = "パスワードを入力してください"; return; }
  const res = await fetch("/api/auth", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: pass })
  });
  if (res.ok) {
    localStorage.setItem("resident_auth", "1");
    document.getElementById("loginScreen").style.display = "none";
    loadBooks();
  } else {
    err.textContent = "❌ パスワードが違います";
    document.getElementById("residentPass").value = "";
  }
});

document.getElementById("residentPass").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("loginBtn").click();
});

document.getElementById("logoutBtn").addEventListener("click", () => {
  if (!confirm("ログアウトしますか？")) return;
  localStorage.removeItem("resident_auth");
  sessionStorage.removeItem("resident_pass");
  sessionStorage.removeItem("board_auth");
  sessionStorage.removeItem("board_pass");
  document.getElementById("loginScreen").style.display = "flex";
  document.getElementById("residentPass").value = "";
  document.getElementById("loginError").textContent = "";
});

// ===== State =====
let currentPage = 1;
let currentKeyword = "";
let currentTotal = 0;
let ratingTarget = null;
let ratingScore = 0;
let currentSort = "";
let logFilter = "all";

// ===== localStorage helpers =====
function getRating(isbn) {
  try { return JSON.parse(localStorage.getItem("rating_" + isbn)) || { score: 0, votes: 0, reviews: [] }; }
  catch { return { score: 0, votes: 0, reviews: [] }; }
}
function saveRating(isbn, score, review) {
  const r = getRating(isbn);
  const newVotes = r.votes + 1;
  const newScore = Math.round(((r.score * r.votes + score) / newVotes) * 10) / 10;
  const reviews = review ? [...r.reviews, review] : r.reviews;
  const updated = { score: newScore, votes: newVotes, reviews };
  localStorage.setItem("rating_" + isbn, JSON.stringify(updated));
  return updated;
}

function isFav(isbn) { return localStorage.getItem("fav_" + isbn) === "1"; }
function toggleFav(isbn) {
  if (isFav(isbn)) localStorage.removeItem("fav_" + isbn);
  else localStorage.setItem("fav_" + isbn, "1");
}
function getFavIsbns() {
  return Object.keys(localStorage).filter(k => k.startsWith("fav_") && localStorage[k] === "1").map(k => k.slice(4));
}

function getReadStatus(isbn) { return localStorage.getItem("read_" + isbn) || ""; }
function setReadStatus(isbn, status) {
  if (status) localStorage.setItem("read_" + isbn, status);
  else localStorage.removeItem("read_" + isbn);
}
function getLogEntries() {
  return Object.keys(localStorage).filter(k => k.startsWith("read_")).map(k => ({
    isbn: k.slice(5), status: localStorage[k]
  }));
}

// ===== Utility =====
function starsHtml(score) {
  if (!score) return '<span class="stars-empty">☆☆☆☆☆</span>';
  const full = Math.round(score);
  return `<span class="stars">${"★".repeat(full)}${"☆".repeat(5 - full)}</span><span class="score-text">${score.toFixed(1)}</span>`;
}

function statusBadge(s) {
  s = (s || "").trim();
  if (s === "貸出中") return `<span class="badge badge-loaned">貸出中</span>`;
  if (s === "利用可能" || s === "在架") return `<span class="badge badge-available">貸出可</span>`;
  return `<span class="badge badge-unknown">${s || "不明"}</span>`;
}

function readStatusBadge(status) {
  const map = { "読んだ": "badge-read", "読書中": "badge-reading", "読みたい": "badge-want" };
  return status ? `<span class="badge ${map[status] || ''}">${status}</span>` : "";
}

// ===== Book card =====
function renderCard(book, opts = {}) {
  const div = document.createElement("div");
  div.className = "book-card";
  const rating = book.rating || getRating(book.isbn);
  const fav = isFav(book.isbn);
  const readStatus = getReadStatus(book.isbn);
  const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${book.isbn}.jpg`;
  const img = book.cover
    ? `<img class="book-cover" src="${book.cover}" alt="${book.title}" loading="lazy" onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.replaceWith(Object.assign(document.createElement('div'),{className:'book-cover-placeholder',textContent:'📖'}));}">`
    : `<div class="book-cover-placeholder">📖</div>`;

  div.innerHTML = `
    <div class="card-cover-wrap">
      ${img}
      <button class="fav-btn ${fav ? 'active' : ''}" data-isbn="${book.isbn}" title="お気に入り">♥</button>
      ${readStatus ? `<div class="read-badge">${readStatus}</div>` : ""}
    </div>
    <div class="book-info">
      <div class="book-title">${book.title}</div>
      <div class="book-author author-link" data-author="${(book.author||"").replace(/"/g,'&quot;')}">${book.author || "著者不明"}</div>
      <div class="book-meta">${book.publisher || ""}</div>
      <div class="card-stars">${starsHtml(rating.score)}</div>
      <div class="avail-status" id="avail-${book.isbn}"></div>
    </div>`;

  div.querySelector(".fav-btn").addEventListener("click", e => {
    e.stopPropagation();
    toggleFav(book.isbn);
    e.currentTarget.classList.toggle("active");
  });
  // 著者名クリックで検索 (#11)
  const authorEl = div.querySelector(".author-link");
  if (authorEl && authorEl.dataset.author) {
    authorEl.addEventListener("click", e => {
      e.stopPropagation();
      const author = authorEl.dataset.author;
      document.getElementById("searchInput").value = author;
      // ジャンルフィルターをリセット
      document.querySelectorAll(".genre-btn").forEach(b => b.classList.remove("active"));
      document.querySelector('.genre-btn[data-genre=""]').classList.add("active");
      loadBooks(author, 1);
      // 蔵書タブに切り替え
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      document.querySelector('.tab-btn[data-tab="books"]').classList.add("active");
      document.getElementById("tab-books").classList.add("active");
    });
  }

  div.addEventListener("click", () => {
    saveRecentBook(book.isbn, book.title, book.cover || "");
    openModal(book.isbn);
  });
  availObserver.observe(div);
  return div;
}

// ダミーのObserver（使用しない）
const availObserver = { observe: () => {} };

// キャッシュ済みの在架状況をグリッドに反映（スクレイピングなし）
async function applyAvailCache(isbns) {
  if (!isbns || !isbns.length) return;
  try {
    const res = await fetch(`/api/availability/cached?isbns=${isbns.join(",")}`);
    const cache = await res.json();
    Object.entries(cache).forEach(([isbn, status]) => {
      const el = document.getElementById("avail-" + isbn);
      if (!el) return;
      if (status === "available") {
        el.innerHTML = '<span class="avail-badge avail-ok">✅ 在架</span>';
      } else if (status === "loaned") {
        el.innerHTML = '<span class="avail-badge avail-ng">📤 貸出中</span>';
      } else {
        el.innerHTML = '';
      }
    });
    // キャッシュにない本は空欄に
    isbns.forEach(isbn => {
      if (!(isbn in cache)) {
        const el = document.getElementById("avail-" + isbn);
        if (el) el.innerHTML = '';
      }
    });
  } catch {}
}

function renderGrid(containerId, books, opts = {}) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = "";
  if (!books || !books.length) {
    grid.innerHTML = '<div class="loading">本が見つかりませんでした。</div>';
    return;
  }
  books.forEach(b => {
    const card = renderCard(b);
    if (opts.showArrived && b.arrived_at) {
      const badge = document.createElement("div");
      badge.className = "arrived-badge";
      const d = new Date(b.arrived_at);
      badge.textContent = `${d.getMonth()+1}/${d.getDate()} 入荷`;
      card.querySelector(".card-cover-wrap").appendChild(badge);
    }
    grid.appendChild(card);
  });
}

// ===== Pagination =====
function renderPagination(containerId, total, page, onPage) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";
  const totalPages = Math.ceil(total / 50);
  if (totalPages <= 1) return;
  const add = (label, p, disabled = false, active = false) => {
    const btn = document.createElement("button");
    btn.className = "page-btn" + (active ? " active" : "");
    btn.textContent = label;
    btn.disabled = disabled;
    if (!disabled) btn.addEventListener("click", () => { onPage(p); window.scrollTo(0, 0); });
    el.appendChild(btn);
  };
  add("＜前", page - 1, page === 1);
  const start = Math.max(1, page - 2), end = Math.min(totalPages, page + 2);
  if (start > 1) { add("1", 1); if (start > 2) el.appendChild(Object.assign(document.createElement("span"), { textContent: "…", className: "page-ellipsis" })); }
  for (let p = start; p <= end; p++) add(String(p), p, false, p === page);
  if (end < totalPages) { el.appendChild(Object.assign(document.createElement("span"), { textContent: "…", className: "page-ellipsis" })); add(String(totalPages), totalPages); }
  add("次＞", page + 1, page === totalPages);
}

// ===== Load books =====
async function loadBooks(keyword = "", page = 1) {
  currentKeyword = keyword;
  currentPage = page;
  document.getElementById("bookGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  document.getElementById("totalCount").textContent = "";
  const res = await fetch(`/api/books?keyword=${encodeURIComponent(keyword)}&page=${page}`);
  const data = await res.json();
  currentTotal = data.total;
  let books = data.books.map(b => ({ ...b, rating: getRating(b.isbn) }));
  if (currentSort === "title") books.sort((a, b) => {
    const noA = !a.author || a.author === "著者不明";
    const noB = !b.author || b.author === "著者不明";
    if (noA !== noB) return noA ? 1 : -1;
    return a.title.localeCompare(b.title, "ja");
  });
  if (currentSort === "author") books.sort((a, b) => authorSortKey(a.author).localeCompare(authorSortKey(b.author), "ja"));
  if (currentSort === "fav") books.sort((a, b) => (isFav(b.isbn) ? 1 : 0) - (isFav(a.isbn) ? 1 : 0));
  document.getElementById("totalCount").textContent = `全 ${data.total.toLocaleString()} 件`;
  renderGrid("bookGrid", books);
  renderPagination("paginationTop", data.total, page, p => loadBooks(keyword, p));
  renderPagination("paginationBottom", data.total, page, p => loadBooks(keyword, p));
  applyAvailCache(data.books.map(b => b.isbn).filter(Boolean));
}

// ===== ジャンル件数バッジ =====
async function loadGenreCounts() {
  try {
    const res = await fetch("/api/genres");
    const data = await res.json();
    const countMap = {};
    data.forEach(r => { if (r.genre) countMap[r.genre] = r.count; });
    // デスクトップ: ボタンにバッジ追加
    document.querySelectorAll(".genre-btn[data-genre]").forEach(btn => {
      const genre = btn.dataset.genre;
      if (!genre) return;
      const cnt = countMap[genre];
      if (!cnt) return;
      const existing = btn.querySelector(".genre-count");
      if (existing) existing.remove();
      const badge = document.createElement("span");
      badge.className = "genre-count";
      badge.textContent = cnt;
      btn.appendChild(badge);
    });
    // モバイル: selectオプションに件数追加
    document.querySelectorAll("#genreSelect option").forEach(opt => {
      const genre = (opt.value || "").split("|")[0];
      if (!genre) return;
      const cnt = countMap[genre];
      if (!cnt) return;
      if (!opt.dataset.baseText) opt.dataset.baseText = opt.textContent;
      opt.textContent = `${opt.dataset.baseText} (${cnt})`;
    });
  } catch (e) {}
}

// ===== 今日の1冊 =====
async function loadTodayBook() {
  try {
    const res = await fetch("/api/today-book");
    const books = await res.json();
    if (!books || !books.length) return;
    const section = document.getElementById("todayBookSection");
    const card = document.getElementById("todayBookCard");
    card.innerHTML = books.map(b => {
      const img = b.cover
        ? `<img class="today-book-cover" src="${b.cover}" alt="${b.title}" onerror="this.outerHTML='<div class=\\'today-book-cover-placeholder\\'>📖</div>'">`
        : `<div class="today-book-cover-placeholder">📖</div>`;
      return `<div class="today-book-inner" data-isbn="${b.isbn}">${img}<div class="today-book-title">${b.title}</div><div class="today-book-author">${b.author || ""}</div></div>`;
    }).join("");
    card.querySelectorAll(".today-book-inner").forEach(el => {
      el.addEventListener("click", () => openModal(el.dataset.isbn));
    });
    section.style.display = "block";
  } catch (e) {}
}

// ===== 最近見た本 =====
function saveRecentBook(isbn, title, cover) {
  if (!isbn) return;
  let recent = [];
  try { recent = JSON.parse(localStorage.getItem("recent_books") || "[]"); } catch {}
  recent = recent.filter(b => b.isbn !== isbn);
  recent.unshift({ isbn, title: title || "", cover: cover || "" });
  localStorage.setItem("recent_books", JSON.stringify(recent.slice(0, 12)));
  renderRecentBooks();
}

function renderRecentBooks() {
  let recent = [];
  try { recent = JSON.parse(localStorage.getItem("recent_books") || "[]"); } catch {}
  const section = document.getElementById("recentBooksSection");
  const row = document.getElementById("recentBooksRow");
  if (!section || !row || !recent.length) { if (section) section.style.display = "none"; return; }
  row.innerHTML = recent.map(b => {
    const img = b.cover
      ? `<img src="${b.cover}" alt="${b.title}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'recent-thumb-placeholder\\'>📖</div>'">`
      : `<div class="recent-thumb-placeholder">📖</div>`;
    return `<div class="recent-thumb" data-isbn="${b.isbn}" title="${b.title}">${img}</div>`;
  }).join("");
  row.querySelectorAll(".recent-thumb").forEach(el => {
    el.addEventListener("click", () => openModal(el.dataset.isbn));
  });
  section.style.display = "";
}

function authorSortKey(author) {
  if (!author || author === "著者不明") return "￿"; // 末尾へ
  // アルファベット始まりは日本語の後ろへ（先頭に"z"プレフィックス）
  if (/^[A-Za-z]/.test(author)) return "z" + author.toLowerCase();
  return author;
}

// ===== ジャンルフィルター =====
let currentGenre = "";  // "" = 通常検索, それ以外 = ジャンルモード

document.getElementById("genreSelect").addEventListener("change", e => {
  const [genre, mode] = e.target.value.split("|");
  currentGenre = (mode === "genre") ? genre : "";
  document.querySelectorAll(".genre-btn").forEach(b => b.classList.remove("active"));
  const matchBtn = document.querySelector(`.genre-btn[data-genre="${genre}"]`);
  if (matchBtn) matchBtn.classList.add("active");
  document.getElementById("searchInput").value = "";
  if (mode === "genre") loadBooksByGenre(genre, 1);
  else loadBooks("", 1);
});

document.querySelectorAll(".genre-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".genre-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const genre = btn.dataset.genre;
    const mode  = btn.dataset.mode;
    currentGenre = (mode === "genre") ? genre : "";
    const sel = document.getElementById("genreSelect");
    const matchOpt = [...sel.options].find(o => o.value === `${genre}|${mode}`);
    if (matchOpt) sel.value = matchOpt.value;
    document.getElementById("searchInput").value = "";
    if (mode === "genre") loadBooksByGenre(genre, 1);
    else loadBooks("", 1);
  });
});

async function loadBooksByGenre(genre, page = 1) {
  currentPage = page;
  document.getElementById("bookGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  document.getElementById("totalCount").textContent = "";
  const res = await fetch(`/api/books/by-genre?genre=${encodeURIComponent(genre)}&page=${page}`);
  const data = await res.json();
  currentTotal = data.total;
  let books = data.books.map(b => ({ ...b, rating: b.rating || getRating(b.isbn) }));
  if (currentSort === "title") books.sort((a, b) => {
    const noA = !a.author || a.author === "著者不明";
    const noB = !b.author || b.author === "著者不明";
    if (noA !== noB) return noA ? 1 : -1;
    return a.title.localeCompare(b.title, "ja");
  });
  if (currentSort === "author") books.sort((a, b) => authorSortKey(a.author).localeCompare(authorSortKey(b.author), "ja"));
  if (currentSort === "fav") books.sort((a, b) => (isFav(b.isbn) ? 1 : 0) - (isFav(a.isbn) ? 1 : 0));
  document.getElementById("totalCount").textContent = `全 ${data.total.toLocaleString()} 件（${genre}）`;
  renderGrid("bookGrid", books);
  renderPagination("paginationTop",    data.total, page, p => loadBooksByGenre(genre, p));
  renderPagination("paginationBottom", data.total, page, p => loadBooksByGenre(genre, p));
  applyAvailCache(data.books.map(b => b.isbn).filter(Boolean));
}

// ===== トップ新着（蔵書タブ最上部） =====
async function loadTopNew() {
  const section = document.getElementById("topNewSection");
  const row = document.getElementById("topNewRow");
  if (!section || !row) return;
  try {
    const res = await fetch("/api/books/new");
    const data = await res.json();
    const books = (data.books || data).slice(0, 10);
    if (!books.length) return;
    row.innerHTML = books.map(b => {
      const cover = b.cover || get_cover_url_js(b.isbn);
      const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
      return `<div class="top-new-item" data-isbn="${b.isbn}">
        <img class="top-new-cover" src="${cover}" alt="${esc(b.title)}" loading="lazy"
          onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.outerHTML='<div class=\\'top-new-placeholder\\'>📖</div>';}">
        <div class="top-new-title">${esc(b.title)}</div>
        <div class="top-new-author">${esc(b.author || "")}</div>
      </div>`;
    }).join("");
    row.querySelectorAll(".top-new-item").forEach(el => {
      el.addEventListener("click", () => openModal(el.dataset.isbn));
    });
    section.style.display = "block";
  } catch(e) {}
}

function get_cover_url_js(isbn) {
  if (!isbn) return "";
  if (isbn.startsWith("978") && isbn.length === 13) {
    const digits = isbn.slice(3, 12);
    let total = 0;
    for (let i = 0; i < digits.length; i++) total += (10 - i) * parseInt(digits[i]);
    const check = (11 - (total % 11)) % 11;
    const isbn10 = digits + (check === 10 ? "X" : String(check));
    return `https://images-na.ssl-images-amazon.com/images/P/${isbn10}.09.LZZZZZZZ.jpg`;
  }
  return `https://ndlsearch.ndl.go.jp/thumbnail/${isbn}.jpg`;
}

// ===== New arrivals =====
async function loadNew() {
  document.getElementById("newGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch(`/api/books/new`);
  const data = await res.json();
  const label = document.getElementById("newSourceLabel");
  if (label) {
    label.textContent = data.source === "registered"
      ? "📥 図書館スタッフが登録した入荷日順です"
      : "📅 OpenBD出版日順（入荷日未登録）";
    label.style.color = data.source === "registered" ? "#3d6b4f" : "#999";
  }
  renderGrid("newGrid", data.books, { showArrived: data.source === "registered" });
  applyAvailCache(data.books.map(b => b.isbn).filter(Boolean));
}

// ===== Favorites =====
async function loadFavorites() {
  const grid = document.getElementById("favGrid");
  const isbns = getFavIsbns();
  if (!isbns.length) { grid.innerHTML = '<div class="loading">お気に入りはまだありません。<br>本のカードの ♥ をタップして追加しましょう！</div>'; return; }
  grid.innerHTML = '<div class="loading">読み込み中…</div>';
  const books = await Promise.all(isbns.map(isbn =>
    fetch(`/api/book/${isbn}`).then(r => r.json()).catch(() => null)
  ));
  renderGrid("favGrid", books.filter(Boolean));
}

// ===== Reading log =====
async function loadLog(filter = "all") {
  logFilter = filter;
  document.querySelectorAll(".log-filter-btn").forEach(b => b.classList.toggle("active", b.dataset.status === filter));
  const grid = document.getElementById("logGrid");
  let entries = getLogEntries();
  if (filter !== "all") entries = entries.filter(e => e.status === filter);
  if (!entries.length) { grid.innerHTML = '<div class="loading">記録がありません。<br>本の詳細画面からステータスを設定できます。</div>'; return; }
  grid.innerHTML = '<div class="loading">読み込み中…</div>';
  const books = await Promise.all(entries.map(e =>
    fetch(`/api/book/${e.isbn}`).then(r => r.json()).then(b => ({ ...b, _status: e.status })).catch(() => null)
  ));
  renderGrid("logGrid", books.filter(Boolean));
}

// ===== Announcements =====
function newsItemHtml(item, showDelete) {
  return `
    <div class="news-card" data-id="${item.id}">
      <div class="news-meta">
        <span class="news-cat cat-${item.category}">${item.category}</span>
        <span class="news-date">${item.created_at.slice(0, 10)}</span>
        ${showDelete ? `<button class="news-del" data-id="${item.id}" title="削除">🗑</button>` : ""}
      </div>
      <div class="news-title">${item.title}</div>
      <div class="news-body">${item.body.replace(/\n/g, "<br>")}</div>
      ${item.image_url ? `<img class="news-img" src="${item.image_url}" alt="画像" onerror="this.style.display='none'">` : ""}
    </div>`;
}

async function loadNews() {
  const list = document.getElementById("newsList");
  if (!list) return;
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/announcements");
  const items = await res.json();
  if (!items.length) { list.innerHTML = '<div class="loading">お知らせはまだありません。</div>'; return; }
  list.innerHTML = items.map(item => newsItemHtml(item, false)).join("");
}

async function loadAdminNews() {
  const list = document.getElementById("adminNewsList");
  if (!list) return;
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/announcements");
  const items = await res.json();
  if (!items.length) { list.innerHTML = '<div class="loading">投稿済みのお知らせはありません。</div>'; return; }
  list.innerHTML = items.map(item => newsItemHtml(item, true)).join("");
  list.querySelectorAll(".news-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pass = prompt("管理者パスワードを入力してください");
      if (!pass) return;
      const r = await fetch(`/api/announcements/${btn.dataset.id}`, {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pass })
      });
      if (r.ok) loadAdminNews(); else alert("パスワードが違います");
    });
  });
}

// ===== Library info =====
function isClosedDay(y, m, d) {
  const date = new Date(y, m, d);
  const dow = date.getDay(); // 0=日,3=水
  // 年末年始: 12/28〜1/3
  if ((m === 11 && d >= 28) || (m === 0 && d <= 3)) return "nenmatsu";
  // 第2・第4水曜日
  if (dow === 3) {
    const weekNum = Math.ceil(d / 7);
    if (weekNum === 2 || weekNum === 4) return "teiky";
  }
  return false;
}

function buildCalendar(y, m) {
  const DAYS = ["月","火","水","木","金","土","日"];
  const first = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0).getDate();
  // 月曜始まり: 0=月…6=日
  let startDow = (first.getDay() + 6) % 7;
  const today = new Date();

  let html = `<div class="lib-cal">
    <div class="lib-cal-nav">
      <button class="lib-cal-btn" id="calPrev">&#8249;</button>
      <span class="lib-cal-month">${y}年${m + 1}月</span>
      <button class="lib-cal-btn" id="calNext">&#8250;</button>
    </div>
    <div class="lib-cal-grid">`;
  DAYS.forEach(d => { html += `<div class="lib-cal-head ${d==="土"?"sat":d==="日"?"sun":""}">${d}</div>`; });
  for (let i = 0; i < startDow; i++) html += `<div class="lib-cal-empty"></div>`;
  for (let d = 1; d <= lastDay; d++) {
    const dow = (new Date(y, m, d).getDay() + 6) % 7; // 0=月
    const closed = isClosedDay(y, m, d);
    const isToday = today.getFullYear()===y && today.getMonth()===m && today.getDate()===d;
    let cls = "lib-cal-day";
    if (dow === 5) cls += " sat";
    if (dow === 6) cls += " sun";
    if (closed) cls += " closed";
    if (isToday) cls += " today";
    const mark = closed ? "×" : d;
    html += `<div class="${cls}" title="${closed==="nenmatsu"?"年末年始休館":closed==="teiky"?"定期休館（第2・第4水曜）":""}">${mark}</div>`;
  }
  html += `</div>
    <div class="lib-cal-legend">
      <span class="lib-cal-closed-dot"></span>× 休館日（第2・第4水曜・年末年始）
    </div>
  </div>`;
  return html;
}

let _calYear, _calMonth;

async function loadInfo() {
  const res = await fetch("/api/library-info");
  const info = await res.json();
  const hoursHtml = info.hours.map(h =>
    `<div class="avail-row"><span>${h.day}</span><span><strong>${h.time}</strong></span></div>`
  ).join("");
  const now = new Date();
  _calYear = now.getFullYear();
  _calMonth = now.getMonth();

  document.getElementById("infoCard").innerHTML = `
    <h2>📍 ${info.name}</h2>
    <div class="info-row"><span class="info-label">所在地</span><span class="info-value">${info.location}</span></div>
    <div class="info-row"><span class="info-label">開館時間</span><span class="info-value">${hoursHtml}</span></div>
    <div class="info-row info-row-cal">
      <span class="info-label">休館日</span>
      <span class="info-value">
        <div class="info-closed-text">${info.closed}</div>
        <div id="libCalWrap">${buildCalendar(_calYear, _calMonth)}</div>
      </span>
    </div>
    <div class="info-source">📌 最新情報は <a href="https://www2.librarylife.net/booksearch?location=0011" target="_blank">図書館生活サイト</a> をご確認ください。</div>`;

  document.getElementById("calPrev").addEventListener("click", () => {
    _calMonth--;
    if (_calMonth < 0) { _calMonth = 11; _calYear--; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth);
    document.getElementById("calPrev").addEventListener("click", arguments.callee);
    bindCalNav();
  });
  document.getElementById("calNext").addEventListener("click", () => {
    _calMonth++;
    if (_calMonth > 11) { _calMonth = 0; _calYear++; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth);
    bindCalNav();
  });
}

function bindCalNav() {
  document.getElementById("calPrev").onclick = () => {
    _calMonth--; if (_calMonth < 0) { _calMonth = 11; _calYear--; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth);
    bindCalNav();
  };
  document.getElementById("calNext").onclick = () => {
    _calMonth++; if (_calMonth > 11) { _calMonth = 0; _calYear++; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth);
    bindCalNav();
  };
}

// ===== Modal =====
async function openModal(isbn) {
  const modal = document.getElementById("modal");
  document.getElementById("modalContent").innerHTML = '<div class="loading">読み込み中…</div>';
  modal.style.display = "flex";
  const res = await fetch(`/api/book/${isbn}`);
  const book = await res.json();
  const rating = getRating(isbn);
  const fav = isFav(isbn);
  const readStatus = getReadStatus(isbn);
  const isbn13 = book.isbn13 || isbn;
  const ndlUrl = `https://ndlsearch.ndl.go.jp/search?q=${encodeURIComponent(book.title || "")}`;
  const meterUrl = `https://bookmeter.com/books/${isbn13}`;
  const libUrl = `https://www2.librarylife.net/booksearch/detail/${isbn}`;
  const tags = [
    book.publisher ? `<span class="tag tag-publisher">${book.publisher}</span>` : "",
    book.pubdate ? `<span class="tag tag-year">${book.pubdate.slice(0,4)}年</span>` : "",
    book.pages && book.pages !== "0" ? `<span class="tag tag-pages">${book.pages}P</span>` : "",
  ].filter(Boolean).join("");
  const availHtml = book.availability && book.availability.length
    ? book.availability.map(a => `<div class="avail-row"><span>${a.library}</span>${statusBadge(a.status)}</div>`).join("")
    : `<div class="avail-row"><span>情報なし</span></div>`;
  const reviewsHtml = rating.reviews && rating.reviews.length
    ? rating.reviews.map(r => `<div class="review-item">💬 ${r}</div>`).join("")
    : `<div class="no-content">まだコメントはありません</div>`;
  const descHtml = book.description
    ? `<div class="modal-section"><h3>📄 内容紹介</h3><p class="book-desc">${book.description}</p></div>` : "";

  document.getElementById("modalContent").innerHTML = `
    <div class="modal-top">
      <div class="modal-cover">${book.cover ? `<img src="${book.cover}" alt="${book.title}" onerror="this.parentElement.innerHTML='<div class=\\'modal-cover-placeholder\\'>📖</div>'">` : '<div class="modal-cover-placeholder">📖</div>'}</div>
      <div class="modal-header">
        <h2>${book.title || "タイトル不明"}</h2>
        <div class="modal-author">${book.author || "著者不明"}</div>
        <div class="modal-tags">${tags}</div>
        <button class="fav-btn-large ${fav ? 'active' : ''}" data-isbn="${isbn}">
          ${fav ? '❤️ お気に入り済み' : '🤍 お気に入りに追加'}
        </button>
      </div>
    </div>

    <div class="modal-section">
      <h3>📚 読書ステータス</h3>
      <div class="read-status-btns">
        ${["読みたい","読書中","読んだ"].map(s => `
          <button class="read-status-btn ${readStatus === s ? 'active' : ''}" data-status="${s}">${s === "読んだ" ? "✅" : s === "読書中" ? "📖" : "🔖"} ${s}</button>
        `).join("")}
        ${readStatus ? `<button class="read-status-btn clear-btn" data-status="">✕ 解除</button>` : ""}
      </div>
    </div>

    <div class="modal-section">
      <h3>⭐ みんなの評価（あなたのデバイス）</h3>
      <div class="big-stars">${rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆"}</div>
      <div class="rating-info">${rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません"}</div>
      <button class="btn-rate" data-isbn="${isbn}">この本を評価する</button>
    </div>

    <div class="modal-section">
      <h3>🏛️ 貸出状況</h3>
      ${availHtml}
    </div>

    ${descHtml}

    <div class="modal-section">
      <h3>💬 コメント</h3>
      ${reviewsHtml}
    </div>

    <div class="modal-section">
      <h3>🔗 外部リンク</h3>
      <div class="external-links">
        <a class="ext-link ext-link-ndl" href="${ndlUrl}" target="_blank">国立国会図書館</a>
        <a class="ext-link ext-link-meter" href="${meterUrl}" target="_blank">読書メーター</a>
        <a class="ext-link ext-link-lib" href="${libUrl}" target="_blank">図書館生活</a>
      </div>
    </div>`;

  document.querySelector(".fav-btn-large").addEventListener("click", e => {
    toggleFav(isbn);
    const active = isFav(isbn);
    e.currentTarget.classList.toggle("active", active);
    e.currentTarget.textContent = active ? "❤️ お気に入り済み" : "🤍 お気に入りに追加";
  });
  document.querySelectorAll(".read-status-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      setReadStatus(isbn, btn.dataset.status);
      openModal(isbn);
    });
  });
  document.querySelector(".btn-rate").addEventListener("click", () => {
    ratingTarget = isbn;
    openRateModal();
  });
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
  // モーダルで在架確認した結果をカードに反映
  const isbns = [...document.querySelectorAll(".avail-status[id^='avail-']")].map(el => el.id.replace("avail-",""));
  if (isbns.length) applyAvailCache(isbns);
}
function openRateModal() {
  ratingScore = 0;
  document.getElementById("reviewText").value = "";
  document.getElementById("rateMsg").textContent = "";
  updateStarUI(0);
  document.getElementById("rateModal").style.display = "flex";
}
function updateStarUI(n) {
  document.querySelectorAll(".star-opt").forEach((el, i) => el.classList.toggle("active", i < n));
}

// ===== Events =====
document.getElementById("searchBtn").addEventListener("click", () => loadBooks(document.getElementById("searchInput").value));
document.getElementById("searchInput").addEventListener("keydown", e => { if (e.key === "Enter") loadBooks(document.getElementById("searchInput").value); });
document.getElementById("modalClose").addEventListener("click", closeModal);
document.getElementById("modal").addEventListener("click", e => { if (e.target === document.getElementById("modal")) closeModal(); });
document.getElementById("rateClose").addEventListener("click", () => { document.getElementById("rateModal").style.display = "none"; });
document.getElementById("rateModal").addEventListener("click", e => { if (e.target === document.getElementById("rateModal")) document.getElementById("rateModal").style.display = "none"; });

document.getElementById("sortSelect").addEventListener("change", e => {
  currentSort = e.target.value;
  loadBooks(currentKeyword, currentPage);
});

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "new") loadNew();
    if (btn.dataset.tab === "fav") loadFavorites();
    if (btn.dataset.tab === "log") loadLog("all");
    if (btn.dataset.tab === "loaned") loadLoanedResident();
    if (btn.dataset.tab === "news") loadNews();
    if (btn.dataset.tab === "info") loadInfo();
    if (btn.dataset.tab === "card") loadCard();
  });
});

document.querySelectorAll(".log-filter-btn").forEach(btn => {
  btn.addEventListener("click", () => loadLog(btn.dataset.status));
});

document.querySelectorAll(".star-opt").forEach(el => {
  el.addEventListener("click", () => { ratingScore = parseInt(el.dataset.v); updateStarUI(ratingScore); });
  el.addEventListener("mouseover", () => updateStarUI(parseInt(el.dataset.v)));
  el.addEventListener("mouseleave", () => updateStarUI(ratingScore));
});

document.getElementById("submitRate").addEventListener("click", () => {
  if (!ratingScore) { document.getElementById("rateMsg").textContent = "星を選んでください"; return; }
  const review = document.getElementById("reviewText").value.trim();
  saveRating(ratingTarget, ratingScore, review);
  document.getElementById("rateMsg").textContent = "✅ 投稿しました！";
  setTimeout(() => {
    document.getElementById("rateModal").style.display = "none";
    if (ratingTarget) openModal(ratingTarget);
  }, 800);
});

// 画像をCanvas経由でリサイズしてbase64に変換（最大幅1000px、JPEG品質0.82）
function resizeImageFile(file, maxWidth = 1000) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxWidth / img.width);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.82));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });
}

let newsImageData = ""; // URL or base64

function clearNewsImage() {
  newsImageData = "";
  document.getElementById("newsImage").value = "";
  document.getElementById("newsImageFile").value = "";
  document.getElementById("newsImageFileName").textContent = "未選択";
  document.getElementById("newsImagePreview").style.display = "none";
  document.getElementById("newsPreviewImg").src = "";
}

function showNewsPreview(src) {
  const preview = document.getElementById("newsImagePreview");
  const img = document.getElementById("newsPreviewImg");
  img.src = src;
  img.onload = () => { preview.style.display = "block"; };
  img.onerror = () => { preview.style.display = "none"; };
}

// URL入力でプレビュー
document.getElementById("newsImage").addEventListener("input", e => {
  const url = e.target.value.trim();
  if (url) {
    newsImageData = url;
    newsImageFile.value = "";
    document.getElementById("newsImageFileName").textContent = "未選択";
    showNewsPreview(url);
  } else {
    newsImageData = "";
    document.getElementById("newsImagePreview").style.display = "none";
  }
});

// ファイル選択でプレビュー
document.getElementById("newsImageFile").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  document.getElementById("newsImageFileName").textContent = file.name;
  document.getElementById("newsImage").value = "";
  newsImageData = await resizeImageFile(file);
  showNewsPreview(newsImageData);
});

document.getElementById("newsClearImg")?.addEventListener("click", clearNewsImage);

document.getElementById("postNews")?.addEventListener("click", async () => {
  const title = document.getElementById("newsTitle").value.trim();
  const body = document.getElementById("newsBody").value.trim();
  const pass = boardPassword;
  const cat = document.getElementById("newsCat").value;
  const image_url = newsImageData || document.getElementById("newsImage").value.trim();
  if (!title || !body) { document.getElementById("newsMsg").textContent = "タイトルと内容を入力してください"; return; }
  const res = await fetch("/api/announcements", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body, category: cat, image_url, password: pass })
  });
  if (res.ok) {
    document.getElementById("newsMsg").textContent = "✅ 投稿しました！";
    document.getElementById("newsTitle").value = "";
    document.getElementById("newsBody").value = "";
    clearNewsImage();
    loadAdminNews();
    loadNews();
  } else {
    document.getElementById("newsMsg").textContent = "❌ パスワードが違います";
  }
});

// ===== Board (理事メニュー) =====
let boardPassword = "";
let issueFilter = "all";

document.getElementById("boardMenuBtn").addEventListener("click", () => {
  if (sessionStorage.getItem("board_auth") === "1") {
    openBoardPanel();
  } else {
    document.getElementById("boardLoginModal").style.display = "flex";
    document.getElementById("boardPass").focus();
  }
});

document.getElementById("boardLoginClose").addEventListener("click", () => {
  document.getElementById("boardLoginModal").style.display = "none";
});

document.getElementById("boardLoginBtn").addEventListener("click", async () => {
  const pass = document.getElementById("boardPass").value;
  const err = document.getElementById("boardLoginError");
  if (!pass) { err.textContent = "パスワードを入力してください"; return; }
  const res = await fetch("/api/board/auth", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: pass})
  });
  if (res.ok) {
    boardPassword = pass;
    sessionStorage.setItem("board_auth", "1");
    sessionStorage.setItem("board_pass", pass);
    document.getElementById("boardLoginModal").style.display = "none";
    document.getElementById("boardPass").value = "";
    openBoardPanel();
  } else {
    err.textContent = "❌ パスワードが違います";
    document.getElementById("boardPass").value = "";
  }
});
document.getElementById("boardPass").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("boardLoginBtn").click();
});

document.getElementById("boardClose").addEventListener("click", () => {
  document.getElementById("boardPanel").style.display = "none";
});

function openBoardPanel() {
  boardPassword = sessionStorage.getItem("board_pass") || "";
  reqAdminPass = boardPassword;  // board password also works for request admin
  document.getElementById("boardPanel").style.display = "flex";
  loadAdminNews();
}

// Board tabs
document.querySelectorAll(".board-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".board-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".board-tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("btab-" + btn.dataset.btab).classList.add("active");
    if (btn.dataset.btab === "adminnews") loadAdminNews();
    if (btn.dataset.btab === "newarrival") loadNewArrivalAdmin();
    if (btn.dataset.btab === "stats") loadStats();
    if (btn.dataset.btab === "calendar") loadCalendar();
    if (btn.dataset.btab === "issues") loadIssues();
    if (btn.dataset.btab === "brequest") loadReqManage();
    if (btn.dataset.btab === "loaned") loadLoanedBooks();
  });
});

// ===== 新着登録（管理者） =====
(function() {
  // 入荷日のデフォルトを今日に設定
  const dateEl = document.getElementById("arrivalDate");
  if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);

  document.getElementById("arrivalLookupBtn")?.addEventListener("click", async () => {
    const isbn = document.getElementById("arrivalIsbn").value.trim().replace(/-/g, "");
    const msg = document.getElementById("arrivalMsg");
    if (!isbn) { msg.textContent = "ISBNを入力してください"; msg.style.color = "#e05"; return; }
    msg.textContent = "検索中…"; msg.style.color = "#888";
    const res = await fetch(`/api/new-arrivals/lookup?isbn=${isbn}`);
    const data = await res.json();
    if (data.title) {
      document.getElementById("arrivalPreviewTitle").textContent = data.title;
      document.getElementById("arrivalPreviewAuthor").textContent = data.author || "";
      const coverEl = document.getElementById("arrivalPreviewCover");
      coverEl.src = data.cover || "";
      coverEl.style.display = data.cover ? "" : "none";
      document.getElementById("arrivalPreview").style.display = "flex";
      msg.textContent = "✅ 本の情報を取得しました";
      msg.style.color = "#3d6b4f";
      document.getElementById("arrivalLookupBtn").dataset.title = data.title;
      document.getElementById("arrivalLookupBtn").dataset.author = data.author || "";
      document.getElementById("arrivalLookupBtn").dataset.publisher = data.publisher || "";
      document.getElementById("arrivalLookupBtn").dataset.cover = data.cover || "";
    } else {
      document.getElementById("arrivalPreview").style.display = "none";
      msg.textContent = "⚠️ OpenBDに情報がありません。ISBNを確認してください";
      msg.style.color = "#e05";
    }
  });

  document.getElementById("arrivalRegisterBtn")?.addEventListener("click", async () => {
    const isbn = document.getElementById("arrivalIsbn").value.trim().replace(/-/g, "");
    const arrived_at = document.getElementById("arrivalDate").value;
    const msg = document.getElementById("arrivalMsg");
    const btn = document.getElementById("arrivalLookupBtn");
    if (!isbn) { msg.textContent = "ISBNを入力してください"; msg.style.color = "#e05"; return; }
    if (!arrived_at) { msg.textContent = "入荷日を入力してください"; msg.style.color = "#e05"; return; }
    const res = await fetch("/api/new-arrivals", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        password: boardPassword, isbn, arrived_at,
        title: btn.dataset.title || "", author: btn.dataset.author || "",
        publisher: btn.dataset.publisher || "", cover: btn.dataset.cover || ""
      })
    });
    if (res.ok) {
      msg.textContent = "✅ 登録しました";
      msg.style.color = "#3d6b4f";
      document.getElementById("arrivalIsbn").value = "";
      document.getElementById("arrivalPreview").style.display = "none";
      btn.dataset.title = btn.dataset.author = btn.dataset.publisher = btn.dataset.cover = "";
      loadNewArrivalAdmin();
    } else {
      msg.textContent = "❌ 登録に失敗しました";
      msg.style.color = "#e05";
    }
  });
})();

async function loadNewArrivalAdmin() {
  const el = document.getElementById("arrivalList");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/new-arrivals");
  const items = await res.json();
  if (!items.length) { el.innerHTML = '<div class="loading">登録された新着図書はありません</div>'; return; }
  el.innerHTML = items.map(r => `
    <div class="arrival-item">
      <img class="arrival-cover" src="${r.cover || ""}" onerror="this.style.display='none'" alt="">
      <div class="arrival-info">
        <div class="arrival-title">${esc(r.title || r.isbn)}</div>
        <div class="arrival-author">${esc(r.author || "")}</div>
        <div class="arrival-date">📅 入荷日：${r.arrived_at}</div>
      </div>
      <button class="arrival-del btn-danger-sm" data-id="${r.id}">削除</button>
    </div>`).join("");
  el.querySelectorAll(".arrival-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("この新着登録を削除しますか？")) return;
      await fetch(`/api/new-arrivals/${btn.dataset.id}`, {
        method: "DELETE", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password: boardPassword})
      });
      loadNewArrivalAdmin();
    });
  });
}

// ===== Issues =====
document.getElementById("issueFormToggle").addEventListener("click", () => {
  const f = document.getElementById("issueForm");
  f.style.display = f.style.display === "none" ? "block" : "none";
});

document.querySelectorAll(".issue-filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".issue-filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    issueFilter = btn.dataset.filter;
    loadIssues();
  });
});

let allIssues = [];

async function loadIssues() {
  const list = document.getElementById("issueList");
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/issues");
  allIssues = await res.json();
  renderIssues();
}

function renderIssues() {
  const list = document.getElementById("issueList");
  let items = issueFilter === "all" ? [...allIssues] : allIssues.filter(i => i.status === issueFilter);
  if (!items.length) { list.innerHTML = '<div class="loading">課題はありません</div>'; return; }
  const priMap = {"高":"🔴","中":"🟡","低":"🟢"};
  const stMap = {"未対応":"issue-new","対応中":"issue-wip","完了":"issue-done"};
  list.innerHTML = items.map((item, idx) => `
    <div class="issue-card ${stMap[item.status]||''}" data-id="${item.id}">
      <div class="issue-meta">
        <span class="issue-pri">${priMap[item.priority]||""} ${item.priority}</span>
        <span class="issue-status-badge">${item.status}</span>
        <span class="issue-date">${item.created_at.slice(0,10)}</span>
        <div class="move-btns">
          <button class="btn-move issue-up" data-id="${item.id}" ${idx===0?"disabled":""} title="上へ">▲</button>
          <button class="btn-move issue-down" data-id="${item.id}" ${idx===items.length-1?"disabled":""} title="下へ">▼</button>
        </div>
        <button class="btn-edit issue-edit-btn" data-id="${item.id}" title="編集">✏️</button>
        <button class="news-del issue-del" data-id="${item.id}" title="削除">🗑</button>
      </div>
      <div class="issue-title issue-view-title" data-id="${item.id}">${item.title}</div>
      <div class="issue-body issue-view-body" data-id="${item.id}">${item.body.replace(/\n/g,"<br>")}</div>
      <div class="issue-edit-form" id="iedit-${item.id}" style="display:none">
        <input class="ie-title" value="${item.title.replace(/"/g,'&quot;')}" placeholder="課題タイトル" />
        <textarea class="ie-body" rows="3">${item.body}</textarea>
        <div class="board-form-row">
          <select class="ie-priority">
            <option value="高" ${item.priority==="高"?"selected":""}>🔴 高</option>
            <option value="中" ${item.priority==="中"?"selected":""}>🟡 中</option>
            <option value="低" ${item.priority==="低"?"selected":""}>🟢 低</option>
          </select>
          <select class="ie-status">
            <option value="未対応" ${item.status==="未対応"?"selected":""}>未対応</option>
            <option value="対応中" ${item.status==="対応中"?"selected":""}>対応中</option>
            <option value="完了" ${item.status==="完了"?"selected":""}>完了</option>
          </select>
        </div>
        <div style="display:flex;gap:8px;margin-top:6px">
          <button class="btn-primary ie-save" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">保存</button>
          <button class="ie-cancel btn-secondary" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">キャンセル</button>
        </div>
      </div>
      <div class="issue-actions issue-view-actions" data-id="${item.id}">
        <button class="issue-act-btn" data-id="${item.id}" data-status="未対応">未対応</button>
        <button class="issue-act-btn" data-id="${item.id}" data-status="対応中">対応中</button>
        <button class="issue-act-btn" data-id="${item.id}" data-status="完了">完了</button>
      </div>
    </div>`).join("");

  // Move up/down handlers (operate on allIssues array)
  list.querySelectorAll(".issue-up").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id);
      const visibleIds = items.map(i => i.id);
      const idx = visibleIds.indexOf(id);
      if (idx <= 0) return;
      const aIdx = allIssues.findIndex(i => i.id === visibleIds[idx]);
      const bIdx = allIssues.findIndex(i => i.id === visibleIds[idx - 1]);
      [allIssues[aIdx], allIssues[bIdx]] = [allIssues[bIdx], allIssues[aIdx]];
      allIssues.forEach((it,i) => it.sort_order = i);
      renderIssues();
      fetch("/api/issues/reorder", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, order: allIssues.map((it,i) => ({id:it.id, sort_order:i}))})
      });
    });
  });
  list.querySelectorAll(".issue-down").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id);
      const visibleIds = items.map(i => i.id);
      const idx = visibleIds.indexOf(id);
      if (idx >= visibleIds.length - 1) return;
      const aIdx = allIssues.findIndex(i => i.id === visibleIds[idx]);
      const bIdx = allIssues.findIndex(i => i.id === visibleIds[idx + 1]);
      [allIssues[aIdx], allIssues[bIdx]] = [allIssues[bIdx], allIssues[aIdx]];
      allIssues.forEach((it,i) => it.sort_order = i);
      renderIssues();
      fetch("/api/issues/reorder", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, order: allIssues.map((it,i) => ({id:it.id, sort_order:i}))})
      });
    });
  });

  list.querySelectorAll(".issue-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      document.getElementById(`iedit-${id}`).style.display = "block";
      list.querySelector(`.issue-view-title[data-id="${id}"]`).style.display = "none";
      list.querySelector(`.issue-view-body[data-id="${id}"]`).style.display = "none";
      list.querySelector(`.issue-view-actions[data-id="${id}"]`).style.display = "none";
    });
  });
  list.querySelectorAll(".ie-cancel").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      document.getElementById(`iedit-${id}`).style.display = "none";
      list.querySelector(`.issue-view-title[data-id="${id}"]`).style.display = "";
      list.querySelector(`.issue-view-body[data-id="${id}"]`).style.display = "";
      list.querySelector(`.issue-view-actions[data-id="${id}"]`).style.display = "";
    });
  });
  list.querySelectorAll(".ie-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const form = document.getElementById(`iedit-${id}`);
      const title = form.querySelector(".ie-title").value.trim();
      const body = form.querySelector(".ie-body").value.trim();
      const priority = form.querySelector(".ie-priority").value;
      const status = form.querySelector(".ie-status").value;
      if (!title) return;
      await fetch(`/api/issues/${id}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, title, body, priority, status})
      });
      loadIssues();
    });
  });
  list.querySelectorAll(".issue-act-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/issues/${btn.dataset.id}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, status: btn.dataset.status})
      });
      loadIssues();
    });
  });
  list.querySelectorAll(".issue-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("この課題を削除しますか？")) return;
      await fetch(`/api/issues/${btn.dataset.id}`, {
        method: "DELETE", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword})
      });
      loadIssues();
    });
  });
}

document.getElementById("submitIssue").addEventListener("click", async () => {
  const title = document.getElementById("issueTitle").value.trim();
  const body = document.getElementById("issueBody").value.trim();
  const priority = document.getElementById("issuePriority").value;
  const status = document.getElementById("issueStatus").value;
  if (!title) { document.getElementById("issueMsg").textContent = "タイトルを入力してください"; return; }
  const res = await fetch("/api/issues", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: boardPassword, title, body, priority, status})
  });
  if (res.ok) {
    document.getElementById("issueMsg").textContent = "✅ 登録しました";
    document.getElementById("issueTitle").value = "";
    document.getElementById("issueBody").value = "";
    loadIssues();
  }
});

// ===== Stats =====
async function loadStats() {
  const el = document.getElementById("statsContent");
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/stats");
  const data = await res.json();
  if (data.error) { el.innerHTML = `<div class="loading">エラー: ${data.error}</div>`; return; }

  el.innerHTML = `
    <p style="font-size:0.8rem;color:#888;margin-bottom:12px">データ取得日：2026年4月12日（全蔵書5,470冊のデータより）</p>
    <div class="stats-summary">
      <div class="stat-card"><div class="stat-num">${data.total.toLocaleString()}</div><div class="stat-label">総蔵書数</div></div>
    </div>
    <div class="stats-charts">
      <div class="chart-box">
        <h4>出版社別冊数（上位50社・全蔵書）</h4>
        <canvas id="pubChart"></canvas>
      </div>
      <div class="chart-box">
        <h4>著者別冊数（上位50名・全蔵書）</h4>
        <canvas id="authChart"></canvas>
      </div>
      <div class="chart-box">
        <h4>ジャンル別冊数（全蔵書）</h4>
        <canvas id="genreChart"></canvas>
      </div>
      <div class="chart-box">
        <h4>形式別冊数</h4>
        <canvas id="fmtChart" height="220"></canvas>
      </div>
    </div>`;

  drawBarChart("pubChart", data.publishers.map(p=>p[0]), data.publishers.map(p=>p[1]));
  drawBarChart("authChart", data.authors.map(a=>a[0]), data.authors.map(a=>a[1]));
  drawBarChart("genreChart", data.genres.map(g=>g[0]), data.genres.map(g=>g[1]));
  drawPieChart("fmtChart", data.formats.map(f=>f[0]), data.formats.map(f=>f[1]));
}

function drawBarChart(id, labels, values) {
  const canvas = document.getElementById(id);
  const ctx = canvas.getContext("2d");
  const W = canvas.offsetWidth || 400;
  canvas.width = W; canvas.height = 220;
  const max = Math.max(...values);
  const barH = 20, gap = 6, labelW = 120, padding = 20;
  const totalH = (barH + gap) * labels.length + padding * 2;
  canvas.height = totalH;
  ctx.clearRect(0, 0, W, totalH);
  const chartW = W - labelW - padding - 40;
  labels.forEach((label, i) => {
    const y = padding + i * (barH + gap);
    ctx.fillStyle = "#555";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(label.length > 12 ? label.slice(0,12)+"…" : label, labelW, y + barH - 4);
    const bw = (values[i] / max) * chartW;
    ctx.fillStyle = "#3d6b4f";
    ctx.fillRect(labelW + 4, y, bw, barH);
    ctx.fillStyle = "#333";
    ctx.textAlign = "left";
    ctx.fillText(values[i], labelW + 4 + bw + 4, y + barH - 4);
  });
}

function drawPieChart(id, labels, values) {
  const canvas = document.getElementById(id);
  const ctx = canvas.getContext("2d");
  const W = canvas.offsetWidth || 300;
  canvas.width = W; canvas.height = 220;
  const total = values.reduce((a,b)=>a+b, 0);
  const cx = 90, cy = 100, r = 80;
  const colors = ["#3d6b4f","#f0a500","#e05050","#5080e0","#a050c0","#50b0a0","#c08030","#707070"];
  let angle = -Math.PI / 2;
  values.forEach((v, i) => {
    const slice = (v / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.closePath();
    ctx.fillStyle = colors[i % colors.length];
    ctx.fill();
    ctx.strokeStyle = "white";
    ctx.lineWidth = 2;
    ctx.stroke();
    angle += slice;
  });
  ctx.font = "11px sans-serif";
  ctx.textAlign = "left";
  labels.forEach((label, i) => {
    const lx = cx * 2 + 20, ly = 20 + i * 22;
    ctx.fillStyle = colors[i % colors.length];
    ctx.fillRect(lx, ly - 10, 14, 14);
    ctx.fillStyle = "#333";
    ctx.fillText(`${label} (${values[i]})`, lx + 18, ly);
  });
}

// ===== Calendar =====
document.getElementById("calFormToggle").addEventListener("click", () => {
  const f = document.getElementById("calForm");
  f.style.display = f.style.display === "none" ? "block" : "none";
  if (f.style.display === "block") {
    document.getElementById("calDate").value = new Date().toISOString().slice(0,10);
  }
});

let allCalItems = [];

async function loadCalendar() {
  const list = document.getElementById("calList");
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/calendar");
  allCalItems = await res.json();
  renderCalendar();
}

function renderCalendar() {
  const list = document.getElementById("calList");
  const items = allCalItems;
  if (!items.length) { list.innerHTML = '<div class="loading">活動記録はまだありません</div>'; return; }
  list.innerHTML = items.map((item, idx) => `
    <div class="cal-card">
      <div class="cal-header">
        <div class="move-btns">
          <button class="btn-move cal-up" data-id="${item.id}" ${idx===0?"disabled":""} title="上へ">▲</button>
          <button class="btn-move cal-down" data-id="${item.id}" ${idx===items.length-1?"disabled":""} title="下へ">▼</button>
        </div>
        <span class="cal-date cal-view-date" data-id="${item.id}">📅 ${item.event_date}</span>
        <span class="cal-title-text cal-view-title" data-id="${item.id}">${item.title}</span>
        <button class="btn-edit cal-edit-btn" data-id="${item.id}" title="編集">✏️</button>
        <button class="news-del cal-del" data-id="${item.id}" title="削除">🗑</button>
      </div>
      ${item.body ? `<div class="cal-body cal-view-body" data-id="${item.id}">${item.body.replace(/\n/g,"<br>")}</div>` : `<div class="cal-view-body" data-id="${item.id}" style="display:none"></div>`}
      ${item.minutes ? `<details class="cal-minutes cal-view-mins" data-id="${item.id}"><summary>📝 議事録を見る</summary><div class="cal-minutes-body">${item.minutes.replace(/\n/g,"<br>")}</div></details>` : `<div class="cal-view-mins" data-id="${item.id}" style="display:none"></div>`}
      <div class="cal-edit-form" id="cedit-${item.id}" style="display:none">
        <input class="ce-title" value="${item.title.replace(/"/g,'&quot;')}" placeholder="イベント名" style="margin-bottom:6px" />
        <input type="date" class="ce-date" value="${item.event_date}" style="margin-bottom:6px" />
        <textarea class="ce-body" rows="2" placeholder="内容・メモ" style="margin-bottom:6px">${item.body||""}</textarea>
        <textarea class="ce-minutes" rows="4" placeholder="議事録（任意）">${item.minutes||""}</textarea>
        <div style="display:flex;gap:8px;margin-top:6px">
          <button class="btn-primary ce-save" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">保存</button>
          <button class="ce-cancel btn-secondary" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">キャンセル</button>
        </div>
      </div>
    </div>`).join("");

  list.querySelectorAll(".cal-up").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id);
      const idx = allCalItems.findIndex(i => i.id === id);
      if (idx <= 0) return;
      [allCalItems[idx], allCalItems[idx-1]] = [allCalItems[idx-1], allCalItems[idx]];
      allCalItems.forEach((it,i) => it.sort_order = i);
      renderCalendar();
      fetch("/api/calendar/reorder", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, order: allCalItems.map((it,i) => ({id:it.id, sort_order:i}))})
      });
    });
  });
  list.querySelectorAll(".cal-down").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id);
      const idx = allCalItems.findIndex(i => i.id === id);
      if (idx >= allCalItems.length - 1) return;
      [allCalItems[idx], allCalItems[idx+1]] = [allCalItems[idx+1], allCalItems[idx]];
      allCalItems.forEach((it,i) => it.sort_order = i);
      renderCalendar();
      fetch("/api/calendar/reorder", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, order: allCalItems.map((it,i) => ({id:it.id, sort_order:i}))})
      });
    });
  });

  list.querySelectorAll(".cal-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      document.getElementById(`cedit-${id}`).style.display = "block";
      list.querySelector(`.cal-view-date[data-id="${id}"]`).style.display = "none";
      list.querySelector(`.cal-view-title[data-id="${id}"]`).style.display = "none";
      list.querySelector(`.cal-view-body[data-id="${id}"]`).style.display = "none";
      list.querySelector(`.cal-view-mins[data-id="${id}"]`).style.display = "none";
    });
  });
  list.querySelectorAll(".ce-cancel").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      document.getElementById(`cedit-${id}`).style.display = "none";
      list.querySelector(`.cal-view-date[data-id="${id}"]`).style.display = "";
      list.querySelector(`.cal-view-title[data-id="${id}"]`).style.display = "";
      list.querySelector(`.cal-view-body[data-id="${id}"]`).style.display = "";
      list.querySelector(`.cal-view-mins[data-id="${id}"]`).style.display = "";
    });
  });
  list.querySelectorAll(".ce-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const form = document.getElementById(`cedit-${id}`);
      const title = form.querySelector(".ce-title").value.trim();
      const event_date = form.querySelector(".ce-date").value;
      const body = form.querySelector(".ce-body").value.trim();
      const minutes = form.querySelector(".ce-minutes").value.trim();
      if (!title) { alert("タイトルを入力してください"); return; }
      btn.textContent = "保存中…"; btn.disabled = true;
      try {
        const res = await fetch(`/api/calendar/${id}`, {
          method: "PATCH", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({password: boardPassword, title, event_date, body, minutes})
        });
        if (!res.ok) { alert("保存に失敗しました（認証エラー）"); btn.textContent = "保存"; btn.disabled = false; return; }
        // 楽観的にローカルデータを更新してすぐ再描画
        const item = allCalItems.find(i => String(i.id) === String(id));
        if (item) { item.title = title; item.event_date = event_date; item.body = body; item.minutes = minutes; }
        renderCalendar();
      } catch(e) {
        alert("通信エラーが発生しました");
        btn.textContent = "保存"; btn.disabled = false;
      }
    });
  });
  list.querySelectorAll(".cal-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("この記録を削除しますか？")) return;
      await fetch(`/api/calendar/${btn.dataset.id}`, {
        method: "DELETE", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword})
      });
      loadCalendar();
    });
  });
}

document.getElementById("submitCal").addEventListener("click", async () => {
  const title = document.getElementById("calTitle").value.trim();
  const event_date = document.getElementById("calDate").value;
  const body = document.getElementById("calBody").value.trim();
  const minutes = document.getElementById("calMinutes").value.trim();
  if (!title || !event_date) { document.getElementById("calMsg").textContent = "タイトルと日付を入力してください"; return; }
  const res = await fetch("/api/calendar", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: boardPassword, title, event_date, body, minutes})
  });
  if (res.ok) {
    document.getElementById("calMsg").textContent = "✅ 登録しました";
    document.getElementById("calTitle").value = "";
    document.getElementById("calBody").value = "";
    document.getElementById("calMinutes").value = "";
    loadCalendar();
  }
});

// Initial load
checkAuth();
loadBooks();
loadTopNew();
// loadTodayBook(); // 表紙ずれ解消まで非表示
renderRecentBooks();
// loadGenreCounts(); // ジャンルフィルター非表示中

// #44 スリープ対策: 4分ごとにpingしてサービスを起こしておく
setInterval(() => fetch("/ping").catch(() => {}), 4 * 60 * 1000);

// ===== Book Requests =====
let residentPassword = sessionStorage.getItem("resident_pass") || "";
let reqAdminPass = "";

// Capture resident password on login
document.getElementById("loginBtn").addEventListener("click", () => {
  residentPassword = document.getElementById("residentPass").value;
  sessionStorage.setItem("resident_pass", residentPassword);
}, true);

// Submit request
// 部屋番号ハイフン自動挿入（1桁目1-5 → "X-"形式）
function setupRoomInput(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("input", (e) => {
    const val = e.target.value;
    // 先頭が1〜5の数字のみの場合だけハイフン自動挿入
    if (/^\d/.test(val) && val[0] >= "1" && val[0] <= "5" && !val.includes("-")) {
      const digits = val.replace(/\D/g, "");
      e.target.value = digits.length >= 2 ? `${digits[0]}-${digits.slice(1)}` : `${digits[0]}-`;
    }
    // 名前など数字以外の入力はそのまま通す
  });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && el.value.endsWith("-")) {
      e.preventDefault();
      el.value = el.value.slice(0, -1);
    }
  });
}
setupRoomInput("reqRoom");
setupRoomInput("fbRoom");

document.getElementById("reqSubmitBtn").addEventListener("click", async () => {
  const title = document.getElementById("reqTitle").value.trim();
  const author = document.getElementById("reqAuthor").value.trim();
  const reason = document.getElementById("reqReason").value.trim();
  const room = document.getElementById("reqRoom").value.trim();
  const msg = document.getElementById("reqMsg");
  if (!title) { msg.textContent = "⚠️ 書名を入力してください"; msg.style.color = "#e05"; return; }
  const btn = document.getElementById("reqSubmitBtn");
  btn.disabled = true; btn.textContent = "送信中…";
  const pass = residentPassword || localStorage.getItem("req_pass") || "proud2525";
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: pass, title, author, reason, room})
  });
  btn.disabled = false; btn.textContent = "📨 リクエストを送る";
  if (res.ok) {
    msg.textContent = "✅ リクエストを送信しました！ありがとうございます。";
    msg.style.color = "#3d6b4f";
    document.getElementById("reqTitle").value = "";
    document.getElementById("reqAuthor").value = "";
    document.getElementById("reqReason").value = "";
    document.getElementById("reqRoom").value = "";
    showReqToast("✅ リクエストを送信しました！");
  } else {
    msg.textContent = "❌ 送信できませんでした。もう一度お試しください。";
    msg.style.color = "#e05";
  }
});

// ===== 図書館へのご要望フォーム =====
document.getElementById("fbSubmitBtn").addEventListener("click", async () => {
  const body = document.getElementById("fbBody").value.trim();
  const room = document.getElementById("fbRoom").value.trim();
  const msg = document.getElementById("fbMsg");
  if (!body) { msg.textContent = "⚠️ ご要望・ご意見を入力してください"; msg.style.color = "#e05"; return; }
  const btn = document.getElementById("fbSubmitBtn");
  btn.disabled = true; btn.textContent = "送信中…";
  const pass = residentPassword || "proud2525";
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: pass, title: "【ご要望・ご意見】" + body.slice(0, 40), author: "", reason: body, room})
  });
  btn.disabled = false; btn.textContent = "📩 送信する";
  if (res.ok) {
    msg.textContent = "✅ 送信しました！ありがとうございます。";
    msg.style.color = "#3d6b4f";
    document.getElementById("fbBody").value = "";
    document.getElementById("fbRoom").value = "";
    showReqToast("✅ ご要望を送信しました！");
  } else {
    msg.textContent = "❌ 送信できませんでした。もう一度お試しください。";
    msg.style.color = "#e05";
  }
});

function getVotedIds() {
  try { return JSON.parse(localStorage.getItem("voted_requests") || "[]"); } catch { return []; }
}
function saveVotedIds(ids) { localStorage.setItem("voted_requests", JSON.stringify(ids)); }

async function loadReqList() {
  const el = document.getElementById("reqList");
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/requests");
  const items = await res.json();
  if (!items.length) { el.innerHTML = '<div class="loading">まだリクエストはありません</div>'; return; }
  const stLabel = {pending:"⏳ 検討中", doing:"🔄 選定中", done:"✅ 入荷済"};
  const stColor = {pending:"#888", doing:"#c07010", done:"#3d8a4f"};
  const votedIds = getVotedIds();
  const sorted = [...items.filter(r=>r.status!=="done"), ...items.filter(r=>r.status==="done")];
  el.innerHTML = sorted.map(r => {
    const voted = votedIds.includes(r.id);
    const votes = r.votes || 0;
    return `
    <div class="req-card" data-id="${r.id}">
      <div class="req-card-header">
        <div class="req-card-left">
          <span class="req-book-title">📖 ${esc(r.title)}</span>
          ${r.author ? `<span class="req-author-badge">著：${esc(r.author)}</span>` : ""}
        </div>
        <span class="req-status-badge" style="color:${stColor[r.status]||"#888"}">${stLabel[r.status]||""}</span>
      </div>
      ${r.reason ? `<div class="req-reason">"${esc(r.reason)}"</div>` : ""}
      ${r.note ? `<div class="req-note">📝 ${esc(r.note)}</div>` : ""}
      <div class="req-card-footer">
        <div class="req-meta">${r.room ? `🏠 ${esc(r.room)}　` : ""}🕐 ${r.created_at.slice(0,10)}</div>
        <button class="req-vote-btn${voted?" req-vote-done":""}" data-id="${r.id}" ${r.status==="done"?"disabled":""}>
          👍 <span class="req-vote-count">${votes}</span>${voted?" 済":" 読みたい"}
        </button>
      </div>
    </div>`;
  }).join("");

  el.querySelectorAll(".req-vote-btn:not([disabled]):not(.req-vote-done)").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = parseInt(btn.dataset.id);
      btn.disabled = true;
      const r = await fetch(`/api/requests/${id}/vote`, {method:"POST"});
      if (r.ok) {
        const data = await r.json();
        btn.classList.add("req-vote-done");
        btn.innerHTML = `👍 <span class="req-vote-count">${data.votes}</span> 済`;
        const ids = getVotedIds();
        if (!ids.includes(id)) { ids.push(id); saveVotedIds(ids); }
      } else { btn.disabled = false; }
    });
  });
}

async function loadReqManage() {
  const el = document.getElementById("reqAdminList");
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/requests");
  const items = await res.json();

  // Summary
  const cnt = {pending:0, doing:0, done:0};
  items.forEach(r => { if (cnt[r.status]!==undefined) cnt[r.status]++; });
  document.getElementById("reqSummary").innerHTML = `
    <div class="req-sum-box"><div class="req-sum-num" style="color:#888">${cnt.pending}</div><div class="req-sum-lbl">⏳ 未対応</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#c07010">${cnt.doing}</div><div class="req-sum-lbl">🔄 検討中</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#3d8a4f">${cnt.done}</div><div class="req-sum-lbl">✅ 完了</div></div>`;

  if (!items.length) { el.innerHTML = '<div class="loading">リクエストはまだありません</div>'; return; }
  el.innerHTML = items.map(r => `
    <div class="req-admin-card">
      <div class="req-admin-card-header">
        <div>
          <div class="req-book-title">📖 ${esc(r.title)} <span class="req-vote-admin">👍 ${r.votes||0}</span></div>
          ${r.author ? `<span class="req-author-badge">著：${esc(r.author)}</span>` : ""}
        </div>
        <button class="news-del req-del" data-id="${r.id}" title="削除">🗑</button>
      </div>
      ${r.reason ? `<div class="req-reason">"${esc(r.reason)}"</div>` : ""}
      <div class="req-meta">${r.room ? `🏠 ${esc(r.room)}　` : ""}🕐 ${r.created_at.slice(0,10)}</div>
      <div class="req-admin-controls">
        <select class="req-status-sel" data-id="${r.id}">
          <option value="pending" ${r.status==="pending"?"selected":""}>⏳ 未対応</option>
          <option value="doing"   ${r.status==="doing"  ?"selected":""}>🔄 検討中</option>
          <option value="done"    ${r.status==="done"   ?"selected":""}>✅ 完了</option>
        </select>
        <input class="req-note-input" type="text" placeholder="管理者メモ（任意）"
          value="${esc(r.note||"")}" data-id="${r.id}" />
      </div>
    </div>`).join("");

  el.querySelectorAll(".req-status-sel").forEach(sel => {
    sel.addEventListener("change", async () => {
      await fetch(`/api/requests/${sel.dataset.id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, status: sel.value})
      });
      loadReqManage();
    });
  });
  el.querySelectorAll(".req-note-input").forEach(inp => {
    const save = async () => {
      await fetch(`/api/requests/${inp.dataset.id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, note: inp.value})
      });
    };
    inp.addEventListener("blur", save);
    inp.addEventListener("keydown", e => { if (e.key==="Enter") { save(); inp.blur(); }});
  });
  el.querySelectorAll(".req-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("このリクエストを削除しますか？")) return;
      await fetch(`/api/requests/${btn.dataset.id}`, {
        method:"DELETE", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass})
      });
      loadReqManage();
    });
  });
}

// ===== クラウド同期 (#6) =====
let cloudUser = null; // {room, pin}

function getCloudUser() {
  try { return JSON.parse(localStorage.getItem("cloud_user")); } catch { return null; }
}
function setCloudUser(u) {
  if (u) localStorage.setItem("cloud_user", JSON.stringify(u));
  else localStorage.removeItem("cloud_user");
  cloudUser = u;
}

function updateSyncUI() {
  const u = getCloudUser();
  const btn = document.getElementById("syncMenuBtn");
  if (u) {
    btn.textContent = "☁️✓";
    btn.title = `同期中（部屋番号：${u.room}）`;
    btn.style.color = "#3d6b4f";
  } else {
    btn.textContent = "☁️";
    btn.title = "クラウド同期";
    btn.style.color = "";
  }
}

async function cloudSync() {
  const u = getCloudUser();
  if (!u) return;
  const favs = getFavIsbns();
  const rlog = {};
  getLogEntries().forEach(e => { rlog[e.isbn] = e.status; });
  const card_url = localStorage.getItem("libraryCardUrl") || "";
  const card_img = localStorage.getItem("libraryCardImage") || "";
  try {
    await fetch("/api/user/sync", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({room: u.room, pin: u.pin, favorites: favs, reading_log: rlog,
        library_card_url: card_url, library_card_image: card_img})
    });
    document.getElementById("syncFavCount").textContent = favs.length;
    document.getElementById("syncLogCount").textContent = Object.keys(rlog).length;
  } catch {}
}

// お気に入り・読書ステータス変更時に自動同期
const _origToggleFav = toggleFav;
function toggleFav(isbn) {
  _origToggleFav(isbn);
  setTimeout(cloudSync, 500);
}
const _origSetReadStatus = setReadStatus;
function setReadStatus(isbn, status) {
  _origSetReadStatus(isbn, status);
  setTimeout(cloudSync, 500);
}

document.getElementById("syncMenuBtn").addEventListener("click", () => {
  const u = getCloudUser();
  if (u) {
    document.getElementById("syncLoginView").style.display = "none";
    document.getElementById("syncLoggedView").style.display = "block";
    document.getElementById("syncRoomLabel").textContent = `部屋番号：${u.room}`;
    const favs = getFavIsbns();
    const rlog = getLogEntries();
    document.getElementById("syncFavCount").textContent = favs.length;
    document.getElementById("syncLogCount").textContent = rlog.length;
  } else {
    document.getElementById("syncLoginView").style.display = "block";
    document.getElementById("syncLoggedView").style.display = "none";
  }
  document.getElementById("syncModal").style.display = "flex";
});

document.getElementById("syncModalClose").addEventListener("click", () => {
  document.getElementById("syncModal").style.display = "none";
});

// クラウド同期の部屋番号もハイフン自動挿入
setupRoomInput("syncRoom");
document.getElementById("syncRoom").addEventListener("input", () => {
  const val = document.getElementById("syncRoom").value;
  const preview = document.getElementById("syncRoomPreview");
  preview.textContent = val.includes("-") && val.length >= 3 ? `→ ${val}` : "";
});

document.getElementById("syncLoginBtn").addEventListener("click", async () => {
  const room = document.getElementById("syncRoom").value.trim();
  const pin  = document.getElementById("syncPin").value.trim();
  const msg  = document.getElementById("syncLoginMsg");
  if (!room || !pin) { msg.textContent = "部屋番号とPINを入力してください"; msg.style.color="#e05"; return; }
  if (pin.length !== 6) { msg.textContent = "PINは6桁の数字を入力してください"; msg.style.color="#e05"; return; }
  document.getElementById("syncLoginBtn").disabled = true;
  document.getElementById("syncLoginBtn").textContent = "確認中…";
  const res = await fetch("/api/user/login", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({room, pin})
  });
  document.getElementById("syncLoginBtn").disabled = false;
  document.getElementById("syncLoginBtn").textContent = "ログイン / 新規登録";
  const data = await res.json();
  if (!res.ok) { msg.textContent = "❌ " + (data.error || "エラー"); msg.style.color="#e05"; return; }

  setCloudUser({room, pin});
  updateSyncUI();

  // クラウドデータをローカルにマージ
  if (!data.is_new) {
    (data.favorites || []).forEach(isbn => localStorage.setItem("fav_" + isbn, "1"));
    Object.entries(data.reading_log || {}).forEach(([isbn, status]) => {
      if (status) localStorage.setItem("read_" + isbn, status);
    });
    if (data.library_card_url) {
      localStorage.setItem("libraryCardUrl", data.library_card_url);
      localStorage.removeItem("libraryCardImage");
    } else if (data.library_card_image) {
      localStorage.setItem("libraryCardImage", data.library_card_image);
      localStorage.removeItem("libraryCardUrl");
    }
    msg.textContent = `✅ ログイン成功！${data.favorites.length}冊のデータを同期しました`;
    msg.style.color = "#3d6b4f";
  } else {
    // 初回: ローカルデータをクラウドにアップロード
    await cloudSync();
    msg.textContent = "✅ 登録完了！データをクラウドに保存しました";
    msg.style.color = "#3d6b4f";
  }
  setTimeout(() => {
    document.getElementById("syncModal").style.display = "none";
    document.getElementById("syncLoginView").style.display = "block";
    document.getElementById("syncLoggedView").style.display = "none";
    document.getElementById("syncRoom").value = "";
    document.getElementById("syncPin").value = "";
    msg.textContent = "";
  }, 1800);
});

document.getElementById("syncNowBtn").addEventListener("click", async () => {
  const msg = document.getElementById("syncMsg");
  msg.textContent = "同期中…"; msg.style.color = "#888";
  await cloudSync();
  msg.textContent = "✅ 同期しました"; msg.style.color = "#3d6b4f";
  setTimeout(() => { msg.textContent = ""; }, 2000);
});

document.getElementById("syncLogoutBtn").addEventListener("click", () => {
  if (!confirm("クラウド同期をログアウトしますか？\nローカルのデータは残ります。")) return;
  setCloudUser(null);
  updateSyncUI();
  document.getElementById("syncModal").style.display = "none";
});

// 起動時にクラウドユーザー状態を反映
cloudUser = getCloudUser();
updateSyncUI();

// ===== パスワード変更 =====
document.getElementById("pwChangeBtn").addEventListener("click", async () => {
  const current = document.getElementById("pwCurrent").value;
  const target = document.getElementById("pwTarget").value;
  const newPw = document.getElementById("pwNew").value;
  const confirm = document.getElementById("pwConfirm").value;
  const msg = document.getElementById("pwMsg");
  if (!current) { msg.textContent = "⚠️ 現在のパスワードを入力してください"; msg.style.color = "#e05"; return; }
  if (!newPw || newPw.length < 4) { msg.textContent = "⚠️ 新しいパスワードは4文字以上で入力してください"; msg.style.color = "#e05"; return; }
  if (newPw !== confirm) { msg.textContent = "⚠️ 確認パスワードが一致しません"; msg.style.color = "#e05"; return; }
  const res = await fetch("/api/admin/change-password", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({current_password: current, target, new_password: newPw})
  });
  const data = await res.json();
  if (res.ok) {
    msg.textContent = "✅ パスワードを変更しました";
    msg.style.color = "#3d6b4f";
    document.getElementById("pwCurrent").value = "";
    document.getElementById("pwNew").value = "";
    document.getElementById("pwConfirm").value = "";
    // If board password was changed, update session
    if (target === "board") {
      boardPassword = newPw;
      sessionStorage.setItem("board_pass", newPw);
    }
  } else {
    msg.textContent = "❌ " + (data.error || "変更できませんでした");
    msg.style.color = "#e05";
  }
});

// ===== 貸出中一覧（入居者タブ） =====
function isbn13ToCoverUrl(isbn13) {
  if (isbn13 && isbn13.startsWith("978") && isbn13.length === 13) {
    const digits = isbn13.slice(3, 12);
    let total = 0;
    for (let i = 0; i < digits.length; i++) total += (10 - i) * parseInt(digits[i]);
    const check = (11 - (total % 11)) % 11;
    const isbn10 = digits + (check === 10 ? "X" : String(check));
    return `https://images-na.ssl-images-amazon.com/images/P/${isbn10}.09.LZZZZZZZ.jpg`;
  }
  return `https://ndlsearch.ndl.go.jp/thumbnail/${isbn13}.jpg`;
}

async function loadLoanedResident() {
  const grid = document.getElementById("loanedResGrid");
  if (!grid) return;
  grid.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/availability/loaned");
  const items = await res.json();
  if (!items.length) {
    grid.innerHTML = '<div class="loading">貸出中の記録がありません。</div>';
    return;
  }
  const countEl = document.getElementById("loanedCount");
  if (countEl) countEl.textContent = `全 ${items.length} 件`;
  // キャッシュデータのみで表示（外部API呼び出しなし）
  const books = items.map(r => ({
    isbn: r.isbn,
    title: r.title || r.isbn,
    author: r.author || "",
    publisher: "",
    cover: isbn13ToCoverUrl(r.isbn),
    rating: { score: 0, votes: 0, reviews: [] }
  }));
  grid.innerHTML = "";
  books.forEach(b => {
    const card = renderCard(b);
    grid.appendChild(card);
    // IDが他タブと重複するため、直接このカード内の要素を更新
    const el = card.querySelector(".avail-status");
    if (el) el.innerHTML = '<span class="avail-badge avail-ng">📤 貸出中</span>';
  });
}

// ===== 貸出中一覧（管理者パネル） =====
async function loadLoanedBooks() {
  const el = document.getElementById("loanedList");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/availability/loaned");
  const items = await res.json();
  if (!items.length) {
    el.innerHTML = '<div class="loading">貸出中の記録がありません。<br>蔵書ページで本を表示すると自動的に在架状況を確認し、ここに記録されます。</div>';
    return;
  }
  el.innerHTML = items.map(r => `
    <div class="req-card" style="cursor:pointer" onclick="openModal('${esc(r.isbn)}');document.getElementById('boardPanel').style.display='none'">
      <div class="req-card-header">
        <div class="req-card-left">
          <span class="req-book-title">📤 ${esc(r.title || r.isbn)}</span>
          ${r.author ? `<span class="req-author-badge">${esc(r.author)}</span>` : ""}
        </div>
        <span class="avail-badge avail-ng" style="font-size:0.78rem">貸出中</span>
      </div>
      <div class="req-meta">ISBN: ${esc(r.isbn)}　🕐 確認日時: ${r.updated_at ? r.updated_at.slice(0,16) : ""}</div>
    </div>`).join("");
}

function esc(s) {
  return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

let reqToastTimer;
function showReqToast(msg) {
  let t = document.getElementById("reqToast");
  if (!t) {
    t = document.createElement("div");
    t.id = "reqToast";
    t.className = "req-toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(reqToastTimer);
  reqToastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}

// ===== 会員証タブ =====
function loadCard() {
  const cardUrl = localStorage.getItem("libraryCardUrl");
  const cardImg = localStorage.getItem("libraryCardImage");

  if (cardUrl || cardImg) {
    document.getElementById("cardView").style.display = "";
    document.getElementById("cardSetup").style.display = "none";

    if (cardUrl) {
      const iframeWrap = document.getElementById("cardIframeWrap");
      const imgWrap = document.getElementById("cardImgWrap");
      iframeWrap.style.display = "";
      imgWrap.style.display = "none";

      const iframe = document.getElementById("cardIframe");
      const errEl = document.getElementById("cardIframeError");
      const openLink = document.getElementById("cardOpenLink");
      openLink.href = cardUrl;
      iframe.src = cardUrl;

      // iframeがX-Frame-Optionsでブロックされた場合のフォールバック
      iframe.onerror = () => {
        iframe.style.display = "none";
        errEl.style.display = "";
      };
      // タイムアウトでもロードできなければエラー表示
      const iframeTimer = setTimeout(() => {
        try {
          const doc = iframe.contentDocument || iframe.contentWindow?.document;
          if (!doc || doc.body === null) {
            iframe.style.display = "none";
            errEl.style.display = "";
          }
        } catch(e) {
          // cross-origin → iframeは機能しているのでそのまま
        }
      }, 5000);
      iframe.onload = () => clearTimeout(iframeTimer);

    } else if (cardImg) {
      document.getElementById("cardIframeWrap").style.display = "none";
      const imgWrap = document.getElementById("cardImgWrap");
      imgWrap.style.display = "";
      document.getElementById("cardImg").src = cardImg;
    }
  } else {
    document.getElementById("cardView").style.display = "none";
    document.getElementById("cardSetup").style.display = "";
  }
}

// ① URLで登録
document.getElementById("cardSaveUrlBtn")?.addEventListener("click", () => {
  const url = document.getElementById("cardUrl").value.trim();
  const msg = document.getElementById("cardUrlMsg");
  if (!url || !url.startsWith("http")) { msg.textContent = "URLを正しく入力してください"; return; }
  localStorage.setItem("libraryCardUrl", url);
  localStorage.removeItem("libraryCardImage");
  msg.textContent = "✅ 登録しました";
  setTimeout(cloudSync, 500);
  setTimeout(() => loadCard(), 400);
});

// ② 画像で登録（Canvas で圧縮してから保存）
document.getElementById("cardSaveImgBtn")?.addEventListener("click", () => {
  const input = document.getElementById("cardImageInput");
  const msg = document.getElementById("cardImgMsg");
  const file = input.files?.[0];
  if (!file) { msg.textContent = "画像ファイルを選んでください"; return; }
  msg.textContent = "圧縮中…";
  const reader = new FileReader();
  reader.onload = (e) => {
    const img = new Image();
    img.onload = () => {
      const MAX = 1200;
      let w = img.width, h = img.height;
      if (w > MAX) { h = Math.round(h * MAX / w); w = MAX; }
      if (h > MAX) { w = Math.round(w * MAX / h); h = MAX; }
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      const compressed = canvas.toDataURL("image/jpeg", 0.75);
      localStorage.setItem("libraryCardImage", compressed);
      localStorage.removeItem("libraryCardUrl");
      const kb = Math.round(compressed.length * 0.75 / 1024);
      msg.textContent = `✅ 登録しました（${kb}KB）`;
      setTimeout(cloudSync, 500);
      setTimeout(() => loadCard(), 400);
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
});

document.getElementById("cardResetBtn")?.addEventListener("click", () => {
  localStorage.removeItem("libraryCardUrl");
  localStorage.removeItem("libraryCardImage");
  loadCard();
});
