// ===== Auth =====
async function checkAuth() {
  const loginScreen = document.getElementById("loginScreen");

  // QRパラメータによる自動ログイン
  const urlParams = new URLSearchParams(window.location.search);
  const qrPw = urlParams.get("qr");
  if (qrPw) {
    const res = await fetch("/api/auth", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: qrPw})
    });
    if (res.ok) {
      localStorage.setItem("resident_auth", "1");
      residentPassword = qrPw;
      sessionStorage.setItem("resident_pass", qrPw);
      // URLからqrパラメータを除去
      window.history.replaceState({}, "", window.location.pathname);
      loginScreen.style.display = "none";
      return;
    }
  }

  if (localStorage.getItem("resident_auth") === "1") {
    loginScreen.style.display = "none";
    return;
  }
  loginScreen.style.display = "flex";
  _initLoginQr();
}

async function _initLoginQr() {
  try {
    const res = await fetch("/api/login-qr-url");
    const data = await res.json();
    const wrap = document.getElementById("loginQrCode");
    if (!wrap || !data.url) return;
    wrap.innerHTML = "";
    new QRCode(wrap, {text: data.url, width: 160, height: 160, correctLevel: QRCode.CorrectLevel.M});
  } catch(e) { /* QR生成失敗時は非表示のまま */ }
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
  return { score: 0, votes: 0, reviews: [] };
}
async function saveRating(isbn, score, review) {
  const res = await fetch("/api/rate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ isbn, score, review })
  });
  return await res.json();
}

function isFav(isbn) { return localStorage.getItem("fav_" + isbn) === "1"; }
function toggleFav(isbn) {
  if (isFav(isbn)) localStorage.removeItem("fav_" + isbn);
  else localStorage.setItem("fav_" + isbn, "1");
  setTimeout(cloudSync, 500);
}
function getFavIsbns() {
  return Object.keys(localStorage).filter(k => k.startsWith("fav_") && localStorage[k] === "1").map(k => k.slice(4));
}

function getReadStatus(isbn) { return localStorage.getItem("read_" + isbn) || ""; }
function setReadStatus(isbn, status) {
  if (status) localStorage.setItem("read_" + isbn, status);
  else localStorage.removeItem("read_" + isbn);
  setTimeout(cloudSync, 500);
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
      <div class="book-title">${esc(book.title)}</div>
      <div class="book-author author-link" data-author="${esc(book.author||"")}">${esc(book.author) || "著者不明"}</div>
      <div class="book-meta">${esc(book.publisher || "")}</div>
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
    openModal(book.isbn, book);
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
    const bookMap = Object.fromEntries(books.map(b => [b.isbn, b]));
    row.querySelectorAll(".top-new-item").forEach(el => {
      el.addEventListener("click", () => openModal(el.dataset.isbn, bookMap[el.dataset.isbn]));
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
  if (label) label.style.display = "none";
  renderGrid("newGrid", data.books, { showArrived: data.source === "registered" });
  applyAvailCache(data.books.map(b => b.isbn).filter(Boolean));
}

// ===== Favorites =====
async function loadFavorites() {
  const grid = document.getElementById("favGrid");
  const isbns = getFavIsbns();
  if (!isbns.length) { grid.innerHTML = '<div class="loading">お気に入りはまだありません。<br>本のカードの ♥ をタップして追加しましょう！</div>'; return; }
  grid.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch(`/api/books/batch?isbns=${isbns.join(",")}`);
  const books = await res.json();
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
  const statusMap = Object.fromEntries(entries.map(e => [e.isbn, e.status]));
  const res = await fetch(`/api/books/batch?isbns=${entries.map(e => e.isbn).join(",")}`);
  const books = (await res.json()).map(b => ({ ...b, _status: statusMap[b.isbn] }));
  renderGrid("logGrid", books.filter(Boolean));
}

// ===== Announcements =====
function newsItemHtml(item, showDelete) {
  const images = item.images || (item.image_url ? [item.image_url] : []);
  const imagesHtml = images.length
    ? `<div class="news-imgs">${images.map(src => `<img class="news-img" src="${src}" alt="お知らせ画像" loading="lazy" onerror="this.style.display='none'">`).join("")}</div>`
    : "";
  const editImagesHtml = images.map((src, i) => `
    <div class="news-edit-img-row" data-index="${i}" style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <img src="${src}" style="width:80px;height:60px;object-fit:cover;border-radius:6px" onerror="this.style.display='none'">
      <button class="news-edit-remove-img" data-id="${item.id}" data-index="${i}" style="padding:4px 10px;border-radius:6px;border:1px solid #e05;color:#e05;background:#fff;cursor:pointer;font-size:0.8rem">🗑 削除</button>
    </div>`).join("");
  return `
    <div class="news-card" data-id="${item.id}">
      <div class="news-meta">
        <span class="news-cat cat-${item.category}">${item.category}</span>
        <span class="news-date">${item.created_at.slice(0, 10)}</span>
        ${showDelete ? `<button class="news-edit" data-id="${item.id}" title="編集">✏️</button><button class="news-del" data-id="${item.id}" title="削除">🗑</button>` : ""}
      </div>
      <div class="news-title">${esc(item.title)}</div>
      ${item.event_date ? `<div class="news-event-date">📅 ${item.event_date}</div>` : ""}
      <div class="news-body">${esc(item.body).replace(/\n/g, "<br>")}</div>
      ${imagesHtml}
      <div class="news-edit-form" id="news-edit-form-${item.id}" style="display:none;margin-top:12px;border-top:1px solid #eee;padding-top:12px">
        <select class="news-edit-cat" data-id="${item.id}" style="margin-bottom:8px;padding:6px;border-radius:6px;border:1px solid #ccc;width:100%" onchange="const w=this.closest('.news-edit-form').querySelector('.news-edit-date-wrap');if(w)w.style.display=(this.value==='イベント'||this.value==='休館')?'block':'none'">
          ${["お知らせ","イベント","休館","新着","図書委員会"].map(c => `<option value="${c}" ${item.category===c?"selected":""}>${c}</option>`).join("")}
        </select>
        <div class="news-edit-date-wrap" style="display:${(item.category==='イベント'||item.category==='休館')?'block':'none'};margin-bottom:8px">
          <label style="font-size:0.82rem;color:#666;display:block;margin-bottom:4px">📅 カレンダーに表示する日付</label>
          <input type="date" class="news-edit-event-date" data-id="${item.id}" value="${item.event_date||''}" style="width:100%;padding:8px;border-radius:6px;border:1px solid #ccc;box-sizing:border-box" />
        </div>
        <input type="text" class="news-edit-title" data-id="${item.id}" value="${item.title.replace(/"/g,'&quot;')}" placeholder="タイトル" style="width:100%;margin-bottom:8px;padding:8px;border-radius:6px;border:1px solid #ccc;box-sizing:border-box">
        <textarea class="news-edit-body" data-id="${item.id}" rows="4" style="width:100%;margin-bottom:8px;padding:8px;border-radius:6px;border:1px solid #ccc;box-sizing:border-box">${item.body}</textarea>
        <div style="margin-bottom:8px">
          <label style="font-size:0.85rem;color:#666;display:block;margin-bottom:6px">📷 画像（複数追加可）</label>
          <div class="news-edit-img-list" data-id="${item.id}">${editImagesHtml}</div>
          <label style="display:inline-block;padding:6px 12px;background:#f0f0f0;border-radius:6px;cursor:pointer;font-size:0.85rem;margin-top:4px">
            ＋ 画像を追加
            <input type="file" class="news-edit-file" data-id="${item.id}" accept="image/*" multiple style="display:none">
          </label>
        </div>
        <div style="display:flex;gap:8px">
          <button class="news-edit-save btn-primary" data-id="${item.id}" style="flex:1">💾 保存</button>
          <button class="news-edit-cancel" data-id="${item.id}" style="flex:1;padding:8px;border-radius:6px;border:1px solid #ccc;cursor:pointer;background:#fff">キャンセル</button>
        </div>
        <p class="news-edit-msg" data-id="${item.id}" style="margin-top:6px;font-size:0.85rem"></p>
      </div>
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
  list.querySelectorAll(".news-edit").forEach(btn => {
    btn.addEventListener("click", () => {
      const form = document.getElementById(`news-edit-form-${btn.dataset.id}`);
      if (form) form.style.display = form.style.display === "none" ? "block" : "none";
    });
  });
  list.querySelectorAll(".news-edit-cancel").forEach(btn => {
    btn.addEventListener("click", () => {
      const form = document.getElementById(`news-edit-form-${btn.dataset.id}`);
      if (form) form.style.display = "none";
    });
  });
  // 既存画像の個別削除
  list.querySelectorAll(".news-edit-remove-img").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.closest(".news-edit-img-row").remove();
    });
  });
  // 画像ファイル追加（複数対応）
  list.querySelectorAll(".news-edit-file").forEach(input => {
    input.addEventListener("change", async (e) => {
      const id = input.dataset.id;
      const imgList = list.querySelector(`.news-edit-img-list[data-id="${id}"]`);
      for (const file of Array.from(e.target.files || [])) {
        const base64 = await resizeImageFile(file);
        const row = document.createElement("div");
        row.className = "news-edit-img-row";
        row.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:6px";
        row.innerHTML = `<img src="${base64}" style="width:80px;height:60px;object-fit:cover;border-radius:6px">
          <button class="news-edit-remove-img-dynamic" style="padding:4px 10px;border-radius:6px;border:1px solid #e05;color:#e05;background:#fff;cursor:pointer;font-size:0.8rem">🗑 削除</button>`;
        row.querySelector(".news-edit-remove-img-dynamic").addEventListener("click", () => row.remove());
        imgList.appendChild(row);
      }
      input.value = "";
    });
  });
  list.querySelectorAll(".news-edit-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const pass = boardPassword;
      if (!pass) { alert("管理者としてログインしてください"); return; }
      const title = list.querySelector(`.news-edit-title[data-id="${id}"]`).value.trim();
      const body = list.querySelector(`.news-edit-body[data-id="${id}"]`).value.trim();
      const category = list.querySelector(`.news-edit-cat[data-id="${id}"]`).value;
      const event_date = list.querySelector(`.news-edit-event-date[data-id="${id}"]`)?.value || "";
      // 残っている画像行からsrcを収集
      const imgList = list.querySelector(`.news-edit-img-list[data-id="${id}"]`);
      const images = Array.from(imgList.querySelectorAll("img")).map(img => img.src).filter(Boolean);
      const msg = list.querySelector(`.news-edit-msg[data-id="${id}"]`);
      if (!title || !body) { msg.textContent = "⚠️ タイトルと本文は必須です"; msg.style.color = "#e05"; return; }
      btn.disabled = true; btn.textContent = "保存中…";
      const r = await fetch(`/api/announcements/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pass, title, body, category, images, event_date })
      });
      btn.disabled = false; btn.textContent = "💾 保存";
      if (r.ok) {
        msg.textContent = "✅ 更新しました";
        msg.style.color = "#3d6b4f";
        setTimeout(() => loadAdminNews(), 800);
      } else {
        msg.textContent = "❌ 失敗しました（パスワードを確認してください）";
        msg.style.color = "#e05";
      }
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

function buildCalendar(y, m, eventsMap) {
  eventsMap = eventsMap || {};
  const DAYS = ["月","火","水","木","金","土","日"];
  const first = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0).getDate();
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
    const dow = (new Date(y, m, d).getDay() + 6) % 7;
    const closed = isClosedDay(y, m, d);
    const isToday = today.getFullYear()===y && today.getMonth()===m && today.getDate()===d;
    const dateKey = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    const evList = eventsMap[dateKey] || [];
    const tempClosed = evList.find(e => e.type === "closed");
    const events = evList.filter(e => e.type === "event");
    let cls = "lib-cal-day";
    if (dow === 5) cls += " sat";
    if (dow === 6) cls += " sun";
    if (closed || tempClosed) cls += " closed";
    if (events.length && !closed && !tempClosed) cls += " has-event";
    if (isToday) cls += " today";
    let sub = "";
    if (closed) {
      sub = `<span class="cal-sub cal-sub-closed">×休館</span>`;
    } else if (tempClosed) {
      const label = tempClosed.title ? tempClosed.title : "臨時休館";
      sub = `<span class="cal-sub cal-sub-closed" title="${esc(label)}">×${esc(label)}</span>`;
    } else if (events.length) {
      sub = events.map(e => `<span class="cal-sub cal-sub-event" title="${esc(e.title)}">★${esc(e.title)}</span>`).join("");
    }
    html += `<div class="${cls}"><span class="cal-day-num">${d}</span>${sub}</div>`;
  }
  html += `</div>
    <div class="lib-cal-legend">
      <span class="lib-cal-closed-dot"></span><span>× 休館日</span>
      <span class="lib-cal-event-dot">★</span><span>イベント</span>
    </div>
  </div>`;
  return html;
}

let _calYear, _calMonth, _calEventsMap = {};

function _buildEventsMap(items) {
  const map = {};
  (items || []).forEach(item => {
    if (!item.event_date) return;
    if (!map[item.event_date]) map[item.event_date] = [];
    map[item.event_date].push({title: item.title, type: item.type || "event"});
  });
  return map;
}

async function loadInfo() {
  const [infoRes, schRes] = await Promise.all([
    fetch("/api/library-info"),
    fetch("/api/lib-schedule")
  ]);
  const info = await infoRes.json();
  const schItems = await schRes.json();
  _calEventsMap = _buildEventsMap(schItems);
  // お知らせのevent_dateもカレンダーにマージ（失敗しても無視）
  try {
    const annRes = await fetch("/api/announcements");
    if (annRes.ok) {
      const annItems = await annRes.json();
      if (Array.isArray(annItems)) {
        annItems.forEach(item => {
          if (!item.event_date) return;
          if (!_calEventsMap[item.event_date]) _calEventsMap[item.event_date] = [];
          const type = item.category === "休館" ? "closed" : "event";
          if (!_calEventsMap[item.event_date].find(e => e.title === item.title)) {
            _calEventsMap[item.event_date].push({title: item.title, type});
          }
        });
      }
    }
  } catch(e) { /* カレンダーへのお知らせマージに失敗しても続行 */ }
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
      <span class="info-label">休館日・イベント</span>
      <span class="info-value">
        <div class="info-closed-text">${info.closed}</div>
        <div id="libCalWrap">${buildCalendar(_calYear, _calMonth, _calEventsMap)}</div>
      </span>
    </div>
    <div class="info-source">📌 最新情報は <a href="https://www2.librarylife.net/booksearch?location=0011" target="_blank">図書館生活サイト</a> をご確認ください。</div>`;

  bindCalNav();
}

function bindCalNav() {
  document.getElementById("calPrev").onclick = () => {
    _calMonth--; if (_calMonth < 0) { _calMonth = 11; _calYear--; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth, _calEventsMap);
    bindCalNav();
  };
  document.getElementById("calNext").onclick = () => {
    _calMonth++; if (_calMonth > 11) { _calMonth = 0; _calYear++; }
    document.getElementById("libCalWrap").innerHTML = buildCalendar(_calYear, _calMonth, _calEventsMap);
    bindCalNav();
  };
}

// ===== Modal =====
function _renderModalContent(isbn, book, rating) {
  const fav = isFav(isbn);
  const readStatus = getReadStatus(isbn);
  const isbn13 = book.isbn13 || isbn;
  const ndlUrl = `https://ndlsearch.ndl.go.jp/search?q=${encodeURIComponent(book.title || "")}`;
  const meterUrl = `https://bookmeter.com/books/${isbn13}`;
  const libUrl = `https://www2.librarylife.net/booksearch/detail/${isbn}`;
  const pubYear = (book.pubdate && parseInt(book.pubdate.slice(0,4)) >= 1900) ? book.pubdate.slice(0,4) + "年" : "";
  const infoRows = [
    book.author     ? ["著者",   esc(book.author)]     : null,
    book.publisher  ? ["出版社", esc(book.publisher)]  : null,
    pubYear         ? ["出版年", pubYear]               : null,
    (book.pages && book.pages !== "0") ? ["ページ数", book.pages + "P"] : null,
    book.format     ? ["形式",   esc(book.format)]     : null,
    (book.size && !book.size.startsWith("0mm")) ? ["サイズ", esc(book.size)] : null,
    isbn13          ? ["ISBN13", isbn13]               : null,
    (book.isbn10 || (isbn13.startsWith("978") ? "" : "")) ? ["ISBN10", esc(book.isbn10 || "")] : null,
  ].filter(r => r && r[1]);
  const infoTable = infoRows.length ? `<dl class="book-info-dl">${infoRows.map(([k,v]) => `<div class="book-info-row"><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>` : "";
  const reviewsHtml = rating.reviews && rating.reviews.length
    ? rating.reviews.map(r => `<div class="review-item">💬 ${esc(r)}</div>`).join("")
    : `<div class="no-content">まだコメントはありません</div>`;
  const descHtml = book.description
    ? `<div class="modal-section"><h3>📄 内容・収録作品</h3><p class="book-desc">${esc(book.description)}</p></div>` : "";

  return `
    <div class="modal-top">
      <div class="modal-cover">${book.cover ? `<img src="${book.cover}" alt="${esc(book.title)}" onerror="this.parentElement.innerHTML='<div class=\\'modal-cover-placeholder\\'>📖</div>'">` : '<div class="modal-cover-placeholder">📖</div>'}</div>
      <div class="modal-header">
        <h2>${esc(book.title) || "タイトル不明"}</h2>
        ${infoTable}
        <button class="fav-btn-large ${fav ? 'active' : ''}" data-isbn="${isbn}">
          ${fav ? '❤️ お気に入り済み' : '🤍 お気に入りに追加'}
        </button>
      </div>
    </div>

    ${descHtml}<div id="modal-desc-placeholder"></div>

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
      <h3>⭐ みんなの評価</h3>
      <div class="big-stars">${rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆"}</div>
      <div class="rating-info">${rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません"}</div>
      <button class="btn-rate" data-isbn="${isbn}">この本を評価する</button>
    </div>

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
    </div>

    <div class="modal-section" id="modal-avail-section">
      <h3>🏛️ 貸出状況</h3>
      <div id="modal-avail-body"><div class="loading" style="font-size:0.85rem;padding:8px 0">取得中…</div></div>
    </div>`;
}

function _bindModalEvents(isbn) {
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

let _modalOpener = null;
async function openModal(isbn, preloadedBook) {
  const modal = document.getElementById("modal");
  _modalOpener = document.activeElement;
  modal.style.display = "flex";
  setTimeout(() => {
    const first = modal.querySelector("button, [tabindex]");
    if (first) first.focus();
  }, 50);

  if (preloadedBook) {
    // 即時表示：カードデータで先にレンダリング（評価は空で初期表示）
    document.getElementById("modalContent").innerHTML = _renderModalContent(isbn, preloadedBook, { score: 0, votes: 0, reviews: [] });
    _bindModalEvents(isbn);

    // 貸出状況・評価・詳細情報を非同期で取得して更新
    try {
      const res = await fetch(`/api/book/${isbn}`);
      const book = await res.json();
      const availEl = document.getElementById("modal-avail-body");
      if (availEl) {
        const availHtml = book.availability && book.availability.length
          ? book.availability.map(a => `<div class="avail-row"><span>${a.library}</span>${statusBadge(a.status)}</div>`).join("")
          : `<div class="avail-row"><span>情報なし</span></div>`;
        availEl.innerHTML = availHtml;
      }
      // 書籍詳細情報（出版年・ISBN等）をフル取得データで更新
      const infoEl = document.querySelector(".book-info-dl");
      if (infoEl) {
        const py = (book.pubdate && parseInt(book.pubdate.slice(0,4)) >= 1900) ? book.pubdate.slice(0,4) + "年" : "";
        const i13 = book.isbn13 || isbn;
        const rows = [
          book.author     ? ["著者",   esc(book.author)]    : null,
          book.publisher  ? ["出版社", esc(book.publisher)] : null,
          py              ? ["出版年", py]                   : null,
          (book.pages && book.pages !== "0") ? ["ページ数", book.pages + "P"] : null,
          book.format     ? ["形式",   esc(book.format)]    : null,
          (book.size && !book.size.startsWith("0mm")) ? ["サイズ", esc(book.size)] : null,
          i13             ? ["ISBN13", i13]                  : null,
          book.isbn10     ? ["ISBN10", esc(book.isbn10)]    : null,
        ].filter(r => r && r[1]);
        infoEl.innerHTML = rows.map(([k,v]) => `<div class="book-info-row"><dt>${k}</dt><dd>${v}</dd></div>`).join("");
      }
      // 評価をサーバーデータで更新
      const rating = book.rating || { score: 0, votes: 0, reviews: [] };
      const starsEl = document.querySelector(".big-stars");
      const ratingInfoEl = document.querySelector(".rating-info");
      if (starsEl) starsEl.textContent = rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆";
      if (ratingInfoEl) ratingInfoEl.textContent = rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません";
      // 内容紹介を追加
      const descPlaceholder = document.getElementById("modal-desc-placeholder");
      if (descPlaceholder && book.description) {
        descPlaceholder.outerHTML = `<div class="modal-section"><h3>📄 内容・収録作品</h3><p class="book-desc">${book.description}</p></div>`;
      }
    } catch(e) {
      const availEl = document.getElementById("modal-avail-body");
      if (availEl) availEl.innerHTML = `<div class="avail-row"><span>取得できませんでした</span></div>`;
    }
  } else {
    // preloadedBookなし（評価後の再表示など）：全データ取得してから表示
    document.getElementById("modalContent").innerHTML = '<div class="loading">読み込み中…</div>';
    const res = await fetch(`/api/book/${isbn}`);
    const book = await res.json();
    const rating = book.rating || { score: 0, votes: 0, reviews: [] };
    const availHtml = book.availability && book.availability.length
      ? book.availability.map(a => `<div class="avail-row"><span>${a.library}</span>${statusBadge(a.status)}</div>`).join("")
      : `<div class="avail-row"><span>情報なし</span></div>`;
    const html = _renderModalContent(isbn, book, rating);
    document.getElementById("modalContent").innerHTML = html;
    document.getElementById("modal-avail-body").innerHTML = availHtml;
    _bindModalEvents(isbn);
  }
}

function closeModal() {
  document.getElementById("modal").style.display = "none";
  if (_modalOpener) { _modalOpener.focus(); _modalOpener = null; }
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
document.getElementById("modalCloseBottom").addEventListener("click", closeModal);
document.getElementById("modal").addEventListener("click", e => { if (e.target === document.getElementById("modal")) closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && document.getElementById("modal").style.display !== "none") closeModal(); });
document.getElementById("rateClose").addEventListener("click", () => { document.getElementById("rateModal").style.display = "none"; });
document.getElementById("rateModal").addEventListener("click", e => { if (e.target === document.getElementById("rateModal")) document.getElementById("rateModal").style.display = "none"; });

document.getElementById("sortSelect").addEventListener("change", e => {
  currentSort = e.target.value;
  loadBooks(currentKeyword, currentPage);
});

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "new") loadNew();
    if (btn.dataset.tab === "fav") loadFavorites();
    if (btn.dataset.tab === "log") loadLog("all");
    if (btn.dataset.tab === "request") {
      document.getElementById("reqMsg").textContent = "";
    }
    if (btn.dataset.tab === "reqlist") loadReqList();
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

document.getElementById("submitRate").addEventListener("click", async () => {
  if (!ratingScore) { document.getElementById("rateMsg").textContent = "星を選んでください"; return; }
  const review = document.getElementById("reviewText").value.trim();
  document.getElementById("rateMsg").textContent = "送信中…";
  await saveRating(ratingTarget, ratingScore, review);
  document.getElementById("rateMsg").textContent = "✅ 投稿しました！";
  setTimeout(() => {
    document.getElementById("rateModal").style.display = "none";
    if (ratingTarget) openModal(ratingTarget);
  }, 800);
});

// 画像をCanvas経由でリサイズしてbase64に変換（最大幅800px、JPEG品質0.72）
function resizeImageFile(file, maxWidth = 800) {
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
        resolve(canvas.toDataURL("image/jpeg", 0.72));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });
}

let newsImages = []; // 投稿フォームの画像リスト（base64 or URL）

function renderNewsImageList() {
  const container = document.getElementById("newsImageList");
  if (!container) return;
  container.innerHTML = newsImages.map((src, i) => `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <img src="${src}" style="width:80px;height:60px;object-fit:cover;border-radius:6px" onerror="this.style.display='none'">
      <button type="button" class="news-img-remove" data-index="${i}" style="padding:4px 10px;border-radius:6px;border:1px solid #e05;color:#e05;background:#fff;cursor:pointer;font-size:0.8rem">🗑 削除</button>
    </div>`).join("");
  container.querySelectorAll(".news-img-remove").forEach(btn => {
    btn.addEventListener("click", () => {
      newsImages.splice(parseInt(btn.dataset.index), 1);
      renderNewsImageList();
    });
  });
}

function clearNewsImage() {
  newsImages = [];
  document.getElementById("newsImage").value = "";
  document.getElementById("newsImageFile").value = "";
  document.getElementById("newsImageFileName").textContent = "未選択";
  document.getElementById("newsImagePreview").style.display = "none";
  document.getElementById("newsPreviewImg").src = "";
  renderNewsImageList();
}

// URL入力でプレビュー
document.getElementById("newsImage").addEventListener("input", e => {
  const url = e.target.value.trim();
  const preview = document.getElementById("newsImagePreview");
  const img = document.getElementById("newsPreviewImg");
  if (url) {
    img.src = url;
    img.onload = () => { preview.style.display = "block"; };
    img.onerror = () => { preview.style.display = "none"; };
  } else {
    preview.style.display = "none";
  }
});

// ファイル選択（複数）でプレビュー
document.getElementById("newsImageFile").addEventListener("change", async (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  document.getElementById("newsImageFileName").textContent = files.map(f => f.name).join(", ");
  document.getElementById("newsImage").value = "";
  document.getElementById("newsImagePreview").style.display = "none";
  for (const file of files) {
    const base64 = await resizeImageFile(file);
    newsImages.push(base64);
  }
  renderNewsImageList();
  e.target.value = "";
});

document.getElementById("newsClearImg")?.addEventListener("click", clearNewsImage);

function updateNewsDateWrap() {
  const cat = document.getElementById("newsCat")?.value;
  const wrap = document.getElementById("newsEventDateWrap");
  if (wrap) wrap.style.display = (cat === "イベント" || cat === "休館") ? "block" : "none";
}
document.getElementById("newsCat")?.addEventListener("change", updateNewsDateWrap);
updateNewsDateWrap();

document.getElementById("postNews")?.addEventListener("click", async () => {
  const title = document.getElementById("newsTitle").value.trim();
  const body = document.getElementById("newsBody").value.trim();
  const pass = boardPassword;
  const cat = document.getElementById("newsCat").value;
  const urlInput = document.getElementById("newsImage").value.trim();
  const images = [...newsImages, ...(urlInput ? [urlInput] : [])];
  if (!title || !body) { document.getElementById("newsMsg").textContent = "タイトルと内容を入力してください"; return; }
  if (!pass) {
    document.getElementById("newsMsg").textContent = "⚠️ セッションが切れています。一度ログアウトして再ログインしてください";
    return;
  }
  const res = await fetch("/api/announcements", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body, category: cat, images, event_date: document.getElementById("newsEventDate")?.value || "", password: pass })
  });
  if (res.ok) {
    document.getElementById("newsMsg").textContent = "✅ 投稿しました！";
    document.getElementById("newsTitle").value = "";
    document.getElementById("newsBody").value = "";
    const edWrap = document.getElementById("newsEventDateWrap");
    if (edWrap) { edWrap.style.display = "none"; document.getElementById("newsEventDate").value = ""; }
    clearNewsImage();
    loadAdminNews();
    loadNews();
  } else if (res.status === 401) {
    document.getElementById("newsMsg").textContent = "❌ パスワードが違います";
  } else {
    const errJson = await res.json().catch(() => ({}));
    document.getElementById("newsMsg").textContent = "❌ 投稿に失敗しました（" + (errJson.error || res.status) + "）";
  }
});

// ===== Board (理事メニュー) =====
let boardPassword = "";
let issueFilter = "all";

let boardSenderName = sessionStorage.getItem("board_name") || "";

// タブ通知
const PAGE_TITLE = document.title;
let notifChatCount = 0;
let notifReqCount = 0;
let lastSeenChatId = null;
let lastSeenReqPending = null;
let reqPollTimer = null;

function updatePageTitle() {
  const total = notifChatCount + notifReqCount;
  if (total > 0) {
    const parts = [];
    if (notifChatCount > 0) parts.push(`💬${notifChatCount}`);
    if (notifReqCount > 0) parts.push(`📬${notifReqCount}`);
    document.title = `(${parts.join(" ")}) ${PAGE_TITLE}`;
  } else {
    document.title = PAGE_TITLE;
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    notifChatCount = 0;
    notifReqCount = 0;
    updatePageTitle();
  }
});

document.getElementById("boardMenuBtn").addEventListener("click", () => {
  if (sessionStorage.getItem("board_auth") === "1") {
    openBoardPanel();
  } else {
    document.getElementById("boardLoginModal").style.display = "flex";
    const nameEl = document.getElementById("boardName");
    if (nameEl) { nameEl.value = boardSenderName; nameEl.focus(); }
    else document.getElementById("boardPass").focus();
  }
});

document.getElementById("boardLoginClose").addEventListener("click", () => {
  document.getElementById("boardLoginModal").style.display = "none";
});

document.getElementById("boardLoginBtn").addEventListener("click", async () => {
  const nameEl = document.getElementById("boardName");
  const name = nameEl ? nameEl.value.trim() : "";
  const pass = document.getElementById("boardPass").value;
  const err = document.getElementById("boardLoginError");
  if (!name) { err.textContent = "お名前を入力してください"; nameEl && nameEl.focus(); return; }
  if (!pass) { err.textContent = "パスワードを入力してください"; return; }
  const res = await fetch("/api/board/auth", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: pass})
  });
  if (res.ok) {
    boardPassword = pass;
    boardSenderName = name;
    sessionStorage.setItem("board_auth", "1");
    sessionStorage.setItem("board_pass", pass);
    sessionStorage.setItem("board_name", name);
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
document.getElementById("boardName") && document.getElementById("boardName").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("boardPass").focus();
});

document.getElementById("boardClose").addEventListener("click", () => {
  document.getElementById("boardPanel").style.display = "none";
  if (reqPollTimer) { clearInterval(reqPollTimer); reqPollTimer = null; }
  lastSeenReqPending = null;
  lastSeenChatId = null;
});

function openBoardPanel() {
  boardPassword = sessionStorage.getItem("board_pass") || "";
  boardSenderName = sessionStorage.getItem("board_name") || "";
  reqAdminPass = boardPassword;
  const lbl = document.getElementById("chatSenderLabel");
  if (lbl) lbl.textContent = boardSenderName ? `👤 ${boardSenderName}` : "";
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
    if (btn.dataset.btab === "libschedule") loadLibSchedule();
    if (btn.dataset.btab === "issues") loadIssues();
    if (btn.dataset.btab === "brequest") loadReqManage();
    if (btn.dataset.btab === "loaned") loadLoanedBooks();
    if (btn.dataset.btab === "staffchat") initStaffChat();
    if (btn.dataset.btab === "settings") loadAdminQr();
    if (btn.dataset.btab === "bookdesc") {
      document.getElementById("descIsbn").value = "";
      document.getElementById("descText").value = "";
      document.getElementById("descCount").textContent = "（0/500文字）";
      document.getElementById("descBookInfo").style.display = "none";
      document.getElementById("descMsg").textContent = "";
    }
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
      <img class="arrival-cover" src="${r.cover || ""}" alt="${esc(r.title || '')}" loading="lazy" onerror="this.style.display='none'">
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
      <div class="issue-title issue-view-title" data-id="${item.id}">${esc(item.title)}</div>
      <div class="issue-body issue-view-body" data-id="${item.id}">${esc(item.body).replace(/\n/g,"<br>")}</div>
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
        <span class="cal-title-text cal-view-title" data-id="${item.id}">${esc(item.title)}</span>
        <button class="btn-edit cal-edit-btn" data-id="${item.id}" title="編集">✏️</button>
        <button class="news-del cal-del" data-id="${item.id}" title="削除">🗑</button>
      </div>
      ${item.body ? `<div class="cal-body cal-view-body" data-id="${item.id}">${esc(item.body).replace(/\n/g,"<br>")}</div>` : `<div class="cal-view-body" data-id="${item.id}" style="display:none"></div>`}
      ${item.minutes ? `<details class="cal-minutes cal-view-mins" data-id="${item.id}"><summary>📝 議事録を見る</summary><div class="cal-minutes-body">${esc(item.minutes).replace(/\n/g,"<br>")}</div></details>` : `<div class="cal-view-mins" data-id="${item.id}" style="display:none"></div>`}
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

// ===== Lib Schedule =====
let allLsItems = [];

document.getElementById("lsFormToggle").addEventListener("click", () => {
  const f = document.getElementById("lsForm");
  f.style.display = f.style.display === "none" ? "block" : "none";
});

async function loadLibSchedule() {
  const list = document.getElementById("lsList");
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/lib-schedule");
  allLsItems = await res.json();
  renderLibSchedule();
}

function renderLibSchedule() {
  const list = document.getElementById("lsList");
  if (!allLsItems.length) { list.innerHTML = '<div class="loading">登録された予定はありません</div>'; return; }
  list.innerHTML = allLsItems.map(item => {
    const badge = item.type === "closed"
      ? `<span class="cal-type-badge closed">🚫 臨時休館</span>`
      : `<span class="cal-type-badge event">📅 イベント</span>`;
    return `
    <div class="cal-card" id="ls-card-${item.id}">
      <div class="cal-header">
        ${badge}
        <span class="ls-view-date">${item.event_date}</span>
        <span class="cal-title-text ls-view-title">${esc(item.title)}</span>
        <button class="btn-edit ls-edit-btn" data-id="${item.id}" title="編集">✏️</button>
        <button class="news-del ls-del" data-id="${item.id}" title="削除">🗑</button>
      </div>
      <div class="ls-edit-form" id="lsedit-${item.id}" style="display:none">
        <select class="lse-type" style="margin-bottom:6px;padding:8px;border-radius:8px;border:1.5px solid #cde;font-size:0.9rem;width:100%">
          <option value="event" ${item.type!=="closed"?"selected":""}>📅 イベント</option>
          <option value="closed" ${item.type==="closed"?"selected":""}>🚫 臨時休館</option>
        </select>
        <input class="lse-title" value="${item.title.replace(/"/g,'&quot;')}" placeholder="タイトル" style="margin-bottom:6px" />
        <input type="date" class="lse-date" value="${item.event_date}" style="margin-bottom:6px" />
        <div style="display:flex;gap:8px;margin-top:6px">
          <button class="btn-primary lse-save" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">保存</button>
          <button class="lse-cancel btn-secondary" data-id="${item.id}" style="font-size:0.83rem;padding:6px 14px">キャンセル</button>
        </div>
      </div>
    </div>`;
  }).join("");

  list.querySelectorAll(".ls-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById(`lsedit-${btn.dataset.id}`).style.display = "block";
    });
  });
  list.querySelectorAll(".lse-cancel").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById(`lsedit-${btn.dataset.id}`).style.display = "none";
    });
  });
  list.querySelectorAll(".lse-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const form = document.getElementById(`lsedit-${id}`);
      const title = form.querySelector(".lse-title").value.trim();
      const event_date = form.querySelector(".lse-date").value;
      const type = form.querySelector(".lse-type").value;
      if (!title || !event_date) { alert("タイトルと日付を入力してください"); return; }
      btn.textContent = "保存中…"; btn.disabled = true;
      const res = await fetch(`/api/lib-schedule/${id}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, title, event_date, type})
      });
      if (!res.ok) { alert("保存に失敗しました"); btn.textContent = "保存"; btn.disabled = false; return; }
      const item = allLsItems.find(i => String(i.id) === String(id));
      if (item) { item.title = title; item.event_date = event_date; item.type = type; }
      renderLibSchedule();
    });
  });
  list.querySelectorAll(".ls-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("この予定を削除しますか？")) return;
      await fetch(`/api/lib-schedule/${btn.dataset.id}`, {
        method: "DELETE", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword})
      });
      loadLibSchedule();
    });
  });
}

document.getElementById("submitLs").addEventListener("click", async () => {
  const title = document.getElementById("lsTitle").value.trim();
  const event_date = document.getElementById("lsDate").value;
  const type = document.getElementById("lsType").value;
  if (!title || !event_date) { document.getElementById("lsMsg").textContent = "タイトルと日付を入力してください"; return; }
  const res = await fetch("/api/lib-schedule", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({password: boardPassword, title, event_date, type})
  });
  if (res.ok) {
    document.getElementById("lsMsg").textContent = "✅ 登録しました";
    document.getElementById("lsTitle").value = "";
    document.getElementById("lsDate").value = "";
    document.getElementById("lsType").value = "event";
    loadLibSchedule();
  }
});

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
loadReqList();
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
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title, author, reason, room})
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
  } else if (res.status === 429) {
    msg.textContent = "⚠️ 送信が多すぎます。しばらく時間をおいてから再試行してください。";
    msg.style.color = "#e07800";
  } else {
    msg.textContent = "❌ 送信できませんでした。もう一度お試しください。";
    msg.style.color = "#e05";
  }
});

// ===== 図書館へのご要望フォーム =====
document.getElementById("fbSubmitBtn").addEventListener("click", async () => {
  const title = document.getElementById("fbTitle").value.trim();
  const body = document.getElementById("fbBody").value.trim();
  const room = document.getElementById("fbRoom").value.trim();
  const msg = document.getElementById("fbMsg");
  if (!title) { msg.textContent = "⚠️ 件名を入力してください"; msg.style.color = "#e05"; return; }
  if (!body) { msg.textContent = "⚠️ 内容を入力してください"; msg.style.color = "#e05"; return; }
  const btn = document.getElementById("fbSubmitBtn");
  btn.disabled = true; btn.textContent = "送信中…";
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title, author: "", reason: body, room, type: "feedback"})
  });
  btn.disabled = false; btn.textContent = "📩 送信する";
  if (res.ok) {
    msg.textContent = "✅ 送信しました！ありがとうございます。";
    msg.style.color = "#3d6b4f";
    document.getElementById("fbTitle").value = "";
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

function reqResidentCardHtml(r, votedIds) {
  const isFb = r.type === "feedback";
  const stLabel = {pending:"⏳ 検討中", approved:"✅ 購入決定", rejected:"❌ 見送り", done:"📦 入荷済",
    fb_received:"📬 受付中", fb_checking:"🔍 確認中", fb_done:"✅ 対応済", fb_rejected:"❌ 見送り",
    fb_pending:"⏳ 検討中", fb_noted:"📝 参考意見として受理", fb_none:"➖ 対応なし"};
  const stColor = {pending:"#888", approved:"#3d8a4f", rejected:"#c00", done:"#555",
    fb_received:"#888", fb_checking:"#5b8dd9", fb_done:"#3d8a4f", fb_rejected:"#c00",
    fb_pending:"#888", fb_noted:"#7a5c9a", fb_none:"#aaa"};
  const voted = votedIds.includes(r.id);
  const votes = r.votes || 0;
  const borderColor = isFb ? "#5b8dd9" : "#3d6b4f";
  const bgColor = isFb ? "#f0f5ff" : "#f2f8f4";
  const voteBtn = isFb ? "" : `
    <button class="req-vote-btn${voted?" req-vote-done":""}" data-id="${r.id}" ${(r.status==="done"||r.status==="rejected")?"disabled":""}>
      👍 <span class="req-vote-count">${votes}</span>${voted?" 済":" 読みたい"}
    </button>`;
  return `
  <div class="req-card" data-id="${r.id}" style="border-left:5px solid ${borderColor};background:${bgColor}">
    <div class="req-card-header">
      <div class="req-card-left">
        <span class="req-book-title">${esc(r.title)}</span>
        ${r.author ? `<span class="req-author-badge">著：${esc(r.author)}</span>` : ""}
      </div>
      <span class="req-status-badge" style="color:${stColor[r.status]||"#888"}">${stLabel[r.status]||""}</span>
    </div>
    ${r.reason ? `<div class="req-reason">"${esc(r.reason)}"</div>` : ""}
    ${r.reply ? `<div class="req-reply">📣 図書館より：${esc(r.reply)}</div>` : ""}
    <div class="req-card-footer">
      <div class="req-meta">🕐 ${(r.created_at||"").slice(0,10)}</div>
      ${voteBtn}
    </div>
  </div>`;
}

function bindVoteEvents(container) {
  container.querySelectorAll(".req-vote-btn:not([disabled]):not(.req-vote-done)").forEach(btn => {
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

async function loadReqList() {
  const elBooks = document.getElementById("reqListBooks");
  const elFb = document.getElementById("reqListFeedback");
  if (!elBooks) return;
  elBooks.innerHTML = '<div class="loading">読み込み中…</div>';
  if (elFb) elFb.innerHTML = '<div class="loading">読み込み中…</div>';
  try {
    const res = await fetch("/api/requests");
    const items = await res.json();
    const votedIds = getVotedIds();
    const order = {pending:0, approved:1, rejected:2, done:3,
      fb_received:0, fb_checking:1, fb_pending:1, fb_done:2, fb_noted:2, fb_rejected:3, fb_none:3};
    const sorted = [...items].sort((a,b) => (order[a.status]??0) - (order[b.status]??0) || (b.votes||0) - (a.votes||0));

    const books = sorted.filter(r => r.type !== "feedback");
    const fbs = sorted.filter(r => r.type === "feedback");

    elBooks.innerHTML = books.length ? books.map(r => reqResidentCardHtml(r, votedIds)).join("") : '<div class="loading">まだ本のリクエストはありません</div>';
    if (elFb) elFb.innerHTML = fbs.length ? fbs.map(r => reqResidentCardHtml(r, votedIds)).join("") : '<div class="loading">まだご要望・ご意見はありません</div>';

    bindVoteEvents(elBooks);
    if (elFb) bindVoteEvents(elFb);

    // サブタブ切り替え
    document.querySelectorAll(".res-subtab-btn").forEach(btn => {
      btn.onclick = () => {
        const isBooks = btn.dataset.subtab === "books";
        document.querySelectorAll(".res-subtab-btn").forEach(b => {
          const bIsBooks = b.dataset.subtab === "books";
          const active = b === btn;
          if (active && bIsBooks) Object.assign(b.style, {background:"#3d6b4f", color:"#fff", borderColor:"#3d6b4f"});
          else if (active) Object.assign(b.style, {background:"#5b8dd9", color:"#fff", borderColor:"#5b8dd9"});
          else if (bIsBooks) Object.assign(b.style, {background:"#f2f8f4", color:"#8aaa94", borderColor:"#c0d9c8"});
          else Object.assign(b.style, {background:"#f5f8ff", color:"#8aabcc", borderColor:"#c0cfe8"});
          b.classList.toggle("active", active);
        });
        elBooks.style.display = isBooks ? "" : "none";
        if (elFb) elFb.style.display = isBooks ? "none" : "";
      };
    });
  } catch(e) {
    elBooks.innerHTML = `<div class="loading">読み込みに失敗しました：${e.message}</div>`;
  }
}

function reqAdminCardHtml(r) {
  const isFb = r.type === "feedback";
  const borderColor = isFb ? "#5b8dd9" : "#3d6b4f";
  const statusOpts = isFb ? `
    <option value="fb_received" ${r.status==="fb_received"||!r.status||r.status==="pending"?"selected":""}>📬 受付中</option>
    <option value="fb_checking" ${r.status==="fb_checking"?"selected":""}>🔍 確認中</option>
    <option value="fb_done"     ${r.status==="fb_done"    ?"selected":""}>✅ 対応済</option>
    <option value="fb_rejected" ${r.status==="fb_rejected"?"selected":""}>❌ 見送り</option>
    <option value="fb_pending"  ${r.status==="fb_pending" ?"selected":""}>⏳ 検討中</option>
    <option value="fb_noted"    ${r.status==="fb_noted"   ?"selected":""}>📝 参考意見として受理</option>
    <option value="fb_none"     ${r.status==="fb_none"    ?"selected":""}>➖ 対応なし</option>
  ` : `
    <option value="pending"  ${r.status==="pending" ||!r.status?"selected":""}>⏳ 検討中</option>
    <option value="approved" ${r.status==="approved"?"selected":""}>✅ 購入決定</option>
    <option value="rejected" ${r.status==="rejected"?"selected":""}>❌ 見送り</option>
    <option value="done"     ${r.status==="done"    ?"selected":""}>📦 入荷済</option>
  `;
  return `
    <div class="req-admin-card" style="border-left:4px solid ${borderColor}">
      <div class="req-admin-card-header">
        <div>
          <div class="req-book-title">${esc(r.title)} ${!isFb?`<span class="req-vote-admin">👍 ${r.votes||0}</span>`:""}</div>
          ${r.author ? `<span class="req-author-badge">著：${esc(r.author)}</span>` : ""}
        </div>
        <button class="news-del req-del" data-id="${r.id}" title="削除">🗑</button>
      </div>
      ${r.reason ? `<div class="req-reason">"${esc(r.reason)}"</div>` : ""}
      <div class="req-meta">${r.room ? `🏠 ${esc(r.room)}　` : ""}🕐 ${(r.created_at||"").slice(0,10)}</div>
      <div class="req-admin-controls">
        <select class="req-status-sel" data-id="${r.id}">${statusOpts}</select>
        <input class="req-note-input" type="text" placeholder="管理者メモ（非公開）"
          value="${esc(r.note||"")}" data-id="${r.id}" />
      </div>
      <div style="margin-top:8px">
        <textarea class="req-reply-input" placeholder="📣 居住者への返答（一覧に表示されます）"
          data-id="${r.id}" rows="3"
          style="width:100%;padding:8px 10px;border-radius:6px;border:1.5px solid #5b8dd9;font-size:0.88rem;font-family:inherit;resize:vertical;box-sizing:border-box;line-height:1.6">${esc(r.reply||"")}</textarea>
        <button class="req-reply-save" data-id="${r.id}" style="margin-top:6px;width:100%;padding:9px 14px;border-radius:6px;background:#5b8dd9;color:#fff;border:none;cursor:pointer;font-size:0.88rem;font-weight:600">返答を保存</button>
      </div>
    </div>`;
}

function bindReqAdminEvents(container) {
  container.querySelectorAll(".req-status-sel").forEach(sel => {
    sel.addEventListener("change", async () => {
      await fetch(`/api/requests/${sel.dataset.id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, status: sel.value})
      });
      loadReqManage();
    });
  });
  container.querySelectorAll(".req-note-input").forEach(inp => {
    const save = async () => {
      await fetch(`/api/requests/${inp.dataset.id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, note: inp.value})
      });
    };
    inp.addEventListener("blur", save);
    inp.addEventListener("keydown", e => { if (e.key==="Enter") { save(); inp.blur(); }});
  });
  container.querySelectorAll(".req-reply-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const reply = container.querySelector(`.req-reply-input[data-id="${id}"]`).value.trim();
      btn.textContent = "保存中…"; btn.disabled = true;
      await fetch(`/api/requests/${id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, reply})
      });
      btn.textContent = "✅ 保存済"; setTimeout(() => { btn.textContent = "返答を保存"; btn.disabled = false; }, 1500);
    });
  });
  container.querySelectorAll(".req-del").forEach(btn => {
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

async function loadReqManage() {
  const elBooks = document.getElementById("reqAdminBooks");
  const elFb = document.getElementById("reqAdminFeedback");
  elBooks.innerHTML = '<div class="loading">読み込み中…</div>';
  elFb.innerHTML = '<div class="loading">読み込み中…</div>';

  const res = await fetch("/api/requests/admin", {headers: {"X-Password": reqAdminPass}});
  const items = await res.json();

  // Summary
  const cnt = {pending:0, approved:0, rejected:0, done:0};
  let fbTotal = 0, fbDone = 0;
  items.forEach(r => {
    if (r.type === "feedback") { fbTotal++; if (r.status==="fb_done") fbDone++; }
    else { if (cnt[r.status]!==undefined) cnt[r.status]++; else cnt.pending++; }
  });
  document.getElementById("reqSummary").innerHTML = `
    <div class="req-sum-box"><div class="req-sum-num" style="color:#888">${cnt.pending}</div><div class="req-sum-lbl">⏳ 検討中</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#3d8a4f">${cnt.approved}</div><div class="req-sum-lbl">✅ 購入決定</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#c00">${cnt.rejected}</div><div class="req-sum-lbl">❌ 見送り</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#555">${cnt.done}</div><div class="req-sum-lbl">📦 入荷済</div></div>
    <div class="req-sum-box" style="border-left:2px solid #e0e0e0;padding-left:12px;margin-left:4px"><div class="req-sum-num" style="color:#5b8dd9">${fbTotal}</div><div class="req-sum-lbl">💬 ご要望</div></div>
    <div class="req-sum-box"><div class="req-sum-num" style="color:#3d8a4f">${fbDone}</div><div class="req-sum-lbl">✅ 対応済</div></div>`;

  const books = items.filter(r => r.type !== "feedback");
  const fbs = items.filter(r => r.type === "feedback");

  elBooks.innerHTML = books.length ? books.map(reqAdminCardHtml).join("") : '<div class="loading">本のリクエストはまだありません</div>';
  elFb.innerHTML = fbs.length ? fbs.map(reqAdminCardHtml).join("") : '<div class="loading">ご要望・ご意見はまだありません</div>';

  bindReqAdminEvents(elBooks);
  bindReqAdminEvents(elFb);

  // サブタブ切り替え
  function applySubtabStyle(activeSubtab) {
    document.querySelectorAll(".req-subtab-btn").forEach(b => {
      const isActive = b.dataset.subtab === activeSubtab;
      const isBooks = b.dataset.subtab === "books";
      if (isActive && isBooks) {
        Object.assign(b.style, {background:"#3d6b4f", color:"#fff", borderColor:"#3d6b4f"});
      } else if (isActive && !isBooks) {
        Object.assign(b.style, {background:"#5b8dd9", color:"#fff", borderColor:"#5b8dd9"});
      } else if (!isActive && isBooks) {
        Object.assign(b.style, {background:"#f2f8f4", color:"#8aaa94", borderColor:"#c0d9c8"});
      } else {
        Object.assign(b.style, {background:"#f5f8ff", color:"#8aabcc", borderColor:"#c0cfe8"});
      }
      b.classList.toggle("active", isActive);
    });
  }
  document.querySelectorAll(".req-subtab-btn").forEach(btn => {
    btn.onclick = () => {
      const isBooks = btn.dataset.subtab === "books";
      applySubtabStyle(btn.dataset.subtab);
      elBooks.style.display = isBooks ? "" : "none";
      elFb.style.display = isBooks ? "none" : "";
    };
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

async function loadDbSize() {
  const display = document.getElementById("dbSizeDisplay");
  if (!display) return;
  display.innerHTML = '<div class="loading">確認中…</div>';
  const res = await fetch(`/api/admin/db-size?password=${encodeURIComponent(boardPassword)}`);
  if (!res.ok) { display.innerHTML = '<p style="color:#e05">❌ 取得できませんでした</p>'; return; }
  const d = await res.json();
  const pct = d.percent;
  const color = pct >= 80 ? "#c00" : pct >= 50 ? "#e07800" : "#3d6b4f";
  const bar = `<div style="background:#eee;border-radius:6px;height:14px;margin:10px 0">
    <div style="background:${color};width:${Math.min(pct,100)}%;height:14px;border-radius:6px;transition:width 0.4s"></div></div>`;
  const tables = (d.tables||[]).map(t => `<tr><td>${t.name}</td><td style="text-align:right">${t.mb} MB</td></tr>`).join("");
  display.innerHTML = `
    <div style="font-size:1.1rem;font-weight:700;color:${color}">${d.total_mb} MB <span style="font-size:0.85rem;font-weight:400;color:#888">/ ${d.limit_mb} MB（${pct}% 使用中）</span></div>
    ${bar}
    ${pct >= 80 ? '<p style="color:#c00;font-size:0.85rem">⚠️ 使用量が80%を超えています。古いお知らせの削除などをご検討ください。</p>' : ''}
    ${tables ? `<table class="guide-table" style="margin-top:12px"><tr><th>テーブル</th><th style="text-align:right">サイズ</th></tr>${tables}</table>` : ""}
    <button class="btn-board-add" id="dbSizeBtn" style="margin-top:12px">🔄 再確認</button>`;
  document.getElementById("dbSizeBtn").addEventListener("click", loadDbSize);
}
document.getElementById("dbSizeBtn").addEventListener("click", loadDbSize);

// ===== Admin QR =====
async function loadAdminQr() {
  const wrap = document.getElementById("adminQrCode");
  if (!wrap) return;
  try {
    const res = await fetch("/api/login-qr-url");
    const data = await res.json();
    wrap.innerHTML = "";
    new QRCode(wrap, {text: data.url, width: 200, height: 200, correctLevel: QRCode.CorrectLevel.M});
  } catch(e) {
    wrap.innerHTML = '<p style="font-size:0.8rem;color:#e05">QR生成に失敗しました</p>';
  }
}

document.getElementById("adminQrPrintBtn").addEventListener("click", async () => {
  const res = await fetch("/api/login-qr-url");
  const data = await res.json();
  const win = window.open("", "_blank");
  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>住民向けQRコード</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"><\/script>
    <style>
      body { font-family: sans-serif; text-align: center; padding: 40px; background: white; }
      h2 { color: #2a4a37; margin-bottom: 8px; }
      p { color: #555; font-size: 0.9rem; margin-bottom: 20px; }
      #qr { display: inline-block; padding: 16px; border: 2px solid #cde; border-radius: 12px; }
      .note { margin-top: 20px; font-size: 0.8rem; color: #888; }
      @media print { button { display: none; } }
    </style>
  </head><body>
    <h2>📚 プラウド船橋コミュニティ図書館</h2>
    <p>QRコードをスキャンするとパスワード入力なしにログインできます</p>
    <div id="qr"></div>
    <p class="note">※ このQRコードはご入居者専用です。外部への共有はご遠慮ください。</p>
    <br><button onclick="window.print()" style="padding:10px 24px;font-size:1rem;cursor:pointer">🖨️ 印刷する</button>
    <script>new QRCode(document.getElementById("qr"), {text: "${data.url}", width: 240, height: 240, correctLevel: QRCode.CorrectLevel.M});<\/script>
  </body></html>`);
  win.document.close();
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

// ===== ライブラリーグループチャット空間 =====
let chatPollTimer = null;
let chatPendingImage = "";  // base64 compressed image

function compressImage(file, maxPx = 1200, quality = 0.72) {
  return new Promise(resolve => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      let w = img.width, h = img.height;
      if (w > maxPx || h > maxPx) {
        if (w > h) { h = Math.round(h * maxPx / w); w = maxPx; }
        else { w = Math.round(w * maxPx / h); h = maxPx; }
      }
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", quality));
    };
    img.src = url;
  });
}

function chatMsgHtml(m) {
  const isMe = m.sender === (boardSenderName || "");
  const time = (m.created_at || "").slice(0, 16).replace("T", " ");
  const avatar = `<div style="width:32px;height:32px;border-radius:50%;background:#3d6b4f;color:#fff;display:flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:700;flex-shrink:0">${esc((m.sender||"?").slice(0,1))}</div>`;
  const bubble = `
    <div style="max-width:72%;background:${isMe?"#3d6b4f":"#fff"};color:${isMe?"#fff":"#333"};padding:${m.image_data?"6px":"9px 13px"};border-radius:${isMe?"14px 14px 4px 14px":"14px 14px 14px 4px"};font-size:0.88rem;line-height:1.5;box-shadow:0 1px 4px rgba(0,0,0,0.08);word-break:break-word;overflow:hidden">
      ${m.image_data ? `<img src="${m.image_data}" class="chat-img-thumb" style="max-width:240px;max-height:240px;border-radius:8px;display:block;cursor:zoom-in">` : ""}
      ${m.message ? `<div style="${m.image_data?"margin-top:6px;padding:0 6px 4px":""}">${esc(m.message)}</div>` : ""}
    </div>`;
  const delBtn = `<button class="chat-del-btn" data-id="${m.id}" title="削除" style="background:none;border:none;cursor:pointer;color:#ccc;font-size:0.82rem;padding:4px 6px;flex-shrink:0;border-radius:6px;transition:background 0.15s" onmouseover="this.style.background='#f0e0e0';this.style.color='#c00'" onmouseout="this.style.background='';this.style.color='#ccc'">🗑</button>`;
  return `
  <div style="display:flex;flex-direction:column;align-items:${isMe?"flex-end":"flex-start"};gap:2px">
    <div style="font-size:0.72rem;color:#aaa;padding:0 6px">${isMe?"":`<b>${esc(m.sender)}</b>　`}${time}</div>
    <div style="display:flex;align-items:flex-end;gap:6px;flex-direction:${isMe?"row-reverse":"row"}">
      ${isMe?"":avatar}
      ${bubble}
      ${delBtn}
    </div>
  </div>`;
}

async function loadChatMessages(scrollToBottom = false) {
  const box = document.getElementById("chatMessages");
  if (!box) return;
  try {
    const res = await fetch(`/api/staff_chat?password=${encodeURIComponent(boardPassword)}`);
    if (!res.ok) return;
    const msgs = await res.json();
    msgs.reverse();
    if (!msgs.length) {
      box.innerHTML = '<div style="text-align:center;color:#bbb;padding:40px 0;font-size:0.9rem">まだメッセージはありません<br>最初のメッセージを送ってみましょう！</div>';
      lastSeenChatId = null;
      return;
    }
    const maxId = Math.max(...msgs.map(m => m.id));
    if (lastSeenChatId === null) {
      lastSeenChatId = maxId;
    } else if (maxId > lastSeenChatId && document.hidden) {
      notifChatCount += msgs.filter(m => m.id > lastSeenChatId).length;
      lastSeenChatId = maxId;
      updatePageTitle();
    } else if (!document.hidden) {
      lastSeenChatId = maxId;
    }
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    box.innerHTML = msgs.map(chatMsgHtml).join("");
    box.querySelectorAll(".chat-del-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("このメッセージを削除しますか？")) return;
        await fetch(`/api/staff_chat/${btn.dataset.id}`, {
          method: "DELETE", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({password: boardPassword})
        });
        loadChatMessages();
      });
    });
    box.querySelectorAll(".chat-img-thumb").forEach(img => {
      img.addEventListener("click", () => {
        const o = document.createElement("div");
        o.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:zoom-out";
        const big = document.createElement("img");
        big.src = img.src;
        big.style.cssText = "max-width:90vw;max-height:90vh;border-radius:8px";
        o.appendChild(big);
        o.addEventListener("click", () => o.remove());
        document.body.appendChild(o);
      });
    });
    if (scrollToBottom || atBottom) box.scrollTop = box.scrollHeight;
  } catch(e) { console.error("chat load error", e); }
}

function setChatImgPreview(dataUrl) {
  chatPendingImage = dataUrl || "";
  const preview = document.getElementById("chatImgPreview");
  const thumb = document.getElementById("chatImgThumb");
  if (!preview || !thumb) return;
  if (dataUrl) {
    thumb.src = dataUrl;
    preview.style.display = "flex";
  } else {
    preview.style.display = "none";
    thumb.src = "";
  }
}

function initStaffChat() {
  const lbl = document.getElementById("chatSenderLabel");
  const name = boardSenderName || sessionStorage.getItem("board_name") || "";
  if (!boardSenderName && name) boardSenderName = name;
  if (lbl) lbl.textContent = boardSenderName ? `👤 ${boardSenderName}` : "👤 名前未設定";

  loadChatMessages(true);
  if (chatPollTimer) clearInterval(chatPollTimer);
  chatPollTimer = setInterval(() => loadChatMessages(), 5000);

  if (!reqPollTimer) {
    reqPollTimer = setInterval(async () => {
      try {
        const res = await fetch("/api/requests");
        if (!res.ok) return;
        const items = await res.json();
        const pendingCount = items.filter(r =>
          r.type !== "feedback" ? r.status === "pending" : (r.status === "fb_received" || r.status === "pending")
        ).length;
        if (lastSeenReqPending === null) {
          lastSeenReqPending = pendingCount;
        } else if (pendingCount > lastSeenReqPending && document.hidden) {
          notifReqCount += pendingCount - lastSeenReqPending;
          lastSeenReqPending = pendingCount;
          updatePageTitle();
        } else if (!document.hidden) {
          lastSeenReqPending = pendingCount;
        }
      } catch(e) {}
    }, 60000);
  }

  const input = document.getElementById("chatInput");
  const sendBtn = document.getElementById("chatSendBtn");
  const imgInput = document.getElementById("chatImgInput");
  const imgClear = document.getElementById("chatImgClear");
  if (!input || !sendBtn) return;

  // 画像選択
  if (imgInput) {
    imgInput.onchange = async () => {
      const file = imgInput.files[0];
      if (!file) return;
      const dataUrl = await compressImage(file);
      setChatImgPreview(dataUrl);
      imgInput.value = "";
    };
  }
  if (imgClear) imgClear.onclick = () => setChatImgPreview("");

  const send = async () => {
    const msg = input.value.trim();
    if (!msg && !chatPendingImage) return;
    const sender = boardSenderName || "匿名";
    input.value = "";
    sendBtn.disabled = true;
    const image_data = chatPendingImage;
    setChatImgPreview("");
    await fetch("/api/staff_chat", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({password: boardPassword, sender, message: msg, image_data})
    });
    sendBtn.disabled = false;
    loadChatMessages(true);
    input.focus();
  };

  sendBtn.onclick = send;
  input.onkeydown = null;
}

// チャットタブを離れたらポーリング停止
document.querySelectorAll(".board-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.dataset.btab !== "staffchat" && chatPollTimer) {
      clearInterval(chatPollTimer);
      chatPollTimer = null;
    }
  });
});

// ===== ウェルカムモーダル =====
let welcomeSlide = 0;
const WELCOME_TOTAL = 4;

function showWelcome() {
  welcomeSlide = 0;
  updateWelcomeSlide();
  document.getElementById("welcomeModal").style.display = "flex";
}

function closeWelcome() {
  document.getElementById("welcomeModal").style.display = "none";
  localStorage.setItem("welcomeSeen", "1");
}

function welcomeNav(dir) {
  welcomeSlide = Math.max(0, Math.min(WELCOME_TOTAL - 1, welcomeSlide + dir));
  updateWelcomeSlide();
}

function updateWelcomeSlide() {
  document.querySelectorAll(".w-slide").forEach(el => {
    el.style.display = parseInt(el.dataset.slide) === welcomeSlide ? "" : "none";
  });
  document.querySelectorAll(".w-dot").forEach(el => {
    el.classList.toggle("active", parseInt(el.dataset.dot) === welcomeSlide);
  });
  const prev = document.getElementById("wPrev");
  const next = document.getElementById("wNext");
  if (prev) prev.style.display = welcomeSlide === 0 ? "none" : "";
  if (next) {
    next.textContent = welcomeSlide === WELCOME_TOTAL - 1 ? "✅ 使ってみる" : "次へ →";
    next.onclick = welcomeSlide === WELCOME_TOTAL - 1 ? closeWelcome : () => welcomeNav(1);
  }
}

// ドットクリック
document.querySelectorAll(".w-dot").forEach(dot => {
  dot.addEventListener("click", () => {
    welcomeSlide = parseInt(dot.dataset.dot);
    updateWelcomeSlide();
  });
});

// 初回訪問時に表示
if (!localStorage.getItem("welcomeSeen")) {
  setTimeout(showWelcome, 800);
}

// ── 書評入力（管理者） ─────────────────────────────────────────────────────
async function lookupBookForDesc() {
  const isbn = document.getElementById("descIsbn").value.trim();
  const info = document.getElementById("descBookInfo");
  if (!isbn) return;
  info.style.display = "none";
  try {
    const res = await fetch(`/api/book/${isbn}`);
    const book = await res.json();
    if (book.title) {
      info.textContent = `📖 ${book.title}${book.author ? " / " + book.author : ""}`;
      info.style.display = "block";
      if (false) { // 既存書評は自動ロードしない（誤上書き防止）
        document.getElementById("descText").value = book.description;
        document.getElementById("descCount").textContent = `（${book.description.length}/500文字）`;
      }
    } else {
      info.textContent = "本が見つかりませんでした";
      info.style.display = "block";
    }
  } catch(e) {
    info.textContent = "取得エラー";
    info.style.display = "block";
  }
}

async function saveBookDesc() {
  const isbn = document.getElementById("descIsbn").value.trim();
  const description = document.getElementById("descText").value.trim();
  const msg = document.getElementById("descMsg");
  if (!isbn) { msg.textContent = "⚠️ ISBNを入力してください"; return; }
  if (!description) { msg.textContent = "⚠️ 書評を入力してください"; return; }
  const pass = sessionStorage.getItem("board_pass") || boardPassword;
  if (!pass) { msg.textContent = "⚠️ 再ログインしてください"; return; }
  msg.textContent = "保存中...";
  try {
    const res = await fetch("/api/book-description", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: pass, isbn, description})
    });
    if (res.ok) {
      msg.textContent = "✅ 保存しました";
      document.getElementById("descIsbn").value = "";
      document.getElementById("descText").value = "";
      document.getElementById("descCount").textContent = "（0/500文字）";
      document.getElementById("descBookInfo").style.display = "none";
      setTimeout(() => { msg.textContent = ""; }, 3000);
    } else {
      const err = await res.json().catch(() => ({}));
      msg.textContent = "❌ 保存失敗: " + (err.error || res.status);
    }
  } catch(e) {
    msg.textContent = "❌ 通信エラー";
  }
}
