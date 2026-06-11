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
  const img = book.cover
    ? `<img class="book-cover" src="${book.cover}" alt="${book.title}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'book-cover-placeholder',textContent:'📖'}))">`
    : `<div class="book-cover-placeholder">📖</div>`;

  div.innerHTML = `
    <div class="card-cover-wrap">
      ${img}
      <button class="fav-btn ${fav ? 'active' : ''}" data-isbn="${book.isbn}" title="お気に入り">♥</button>
      ${readStatus ? `<div class="read-badge">${readStatus}</div>` : ""}
    </div>
    <div class="book-info">
      <div class="book-title">${book.title}</div>
      <div class="book-author">${book.author || "著者不明"}</div>
      <div class="book-meta">${book.publisher || ""}</div>
      <div class="card-stars">${starsHtml(rating.score)}</div>
    </div>`;

  div.querySelector(".fav-btn").addEventListener("click", e => {
    e.stopPropagation();
    toggleFav(book.isbn);
    e.currentTarget.classList.toggle("active");
  });
  div.addEventListener("click", () => openModal(book.isbn));
  return div;
}

function renderGrid(containerId, books) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = "";
  if (!books || !books.length) {
    grid.innerHTML = '<div class="loading">本が見つかりませんでした。</div>';
    return;
  }
  books.forEach(b => grid.appendChild(renderCard(b)));
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
  if (currentSort === "title") books.sort((a, b) => a.title.localeCompare(b.title, "ja"));
  if (currentSort === "author") books.sort((a, b) => a.author.localeCompare(b.author, "ja"));
  if (currentSort === "fav") books.sort((a, b) => (isFav(b.isbn) ? 1 : 0) - (isFav(a.isbn) ? 1 : 0));
  document.getElementById("totalCount").textContent = `全 ${data.total.toLocaleString()} 件`;
  renderGrid("bookGrid", books);
  renderPagination("paginationTop", data.total, page, p => loadBooks(keyword, p));
  renderPagination("paginationBottom", data.total, page, p => loadBooks(keyword, p));
}

// ===== New arrivals =====
async function loadNew() {
  document.getElementById("newGrid").innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch(`/api/books?keyword=&page=1`);
  const data = await res.json();
  renderGrid("newGrid", data.books.slice(0, 20));
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
async function loadNews() {
  const list = document.getElementById("newsList");
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/announcements");
  const items = await res.json();
  if (!items.length) { list.innerHTML = '<div class="loading">お知らせはまだありません。</div>'; return; }
  list.innerHTML = items.map(item => `
    <div class="news-card" data-id="${item.id}">
      <div class="news-meta">
        <span class="news-cat cat-${item.category}">${item.category}</span>
        <span class="news-date">${item.created_at.slice(0, 10)}</span>
        <button class="news-del" data-id="${item.id}" title="削除">🗑</button>
      </div>
      <div class="news-title">${item.title}</div>
      <div class="news-body">${item.body.replace(/\n/g, "<br>")}</div>
      ${item.image_url ? `<img class="news-img" src="${item.image_url}" alt="画像" onerror="this.style.display='none'">` : ""}
    </div>`).join("");
  list.querySelectorAll(".news-del").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pass = prompt("管理者パスワードを入力してください");
      if (!pass) return;
      const r = await fetch(`/api/announcements/${btn.dataset.id}`, {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pass })
      });
      if (r.ok) loadNews(); else alert("パスワードが違います");
    });
  });
}

// ===== Library info =====
async function loadInfo() {
  const res = await fetch("/api/library-info");
  const info = await res.json();
  const hoursHtml = info.hours.map(h =>
    `<div class="avail-row"><span>${h.day}</span><span><strong>${h.time}</strong></span></div>`
  ).join("");
  document.getElementById("infoCard").innerHTML = `
    <h2>📍 ${info.name}</h2>
    <div class="info-row"><span class="info-label">所在地</span><span class="info-value">${info.location}</span></div>
    <div class="info-row"><span class="info-label">開館時間</span><span class="info-value">${hoursHtml}</span></div>
    <div class="info-row"><span class="info-label">休館日</span><span class="info-value">${info.closed}</span></div>
    <div class="info-source">📌 最新情報は <a href="https://www2.librarylife.net/booksearch?location=0011" target="_blank">図書館生活サイト</a> をご確認ください。</div>`;
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

function closeModal() { document.getElementById("modal").style.display = "none"; }
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
    if (btn.dataset.tab === "news") loadNews();
    if (btn.dataset.tab === "info") loadInfo();
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

// Admin panel
document.getElementById("adminToggle").addEventListener("click", () => {
  const p = document.getElementById("adminPanel");
  p.style.display = p.style.display === "none" ? "block" : "none";
});
document.getElementById("postNews").addEventListener("click", async () => {
  const title = document.getElementById("newsTitle").value.trim();
  const body = document.getElementById("newsBody").value.trim();
  const pass = document.getElementById("adminPass").value;
  const cat = document.getElementById("newsCat").value;
  const image_url = document.getElementById("newsImage").value.trim();
  if (!title || !body) { document.getElementById("newsMsg").textContent = "タイトルと内容を入力してください"; return; }
  const res = await fetch("/api/announcements", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body, category: cat, image_url, password: pass })
  });
  if (res.ok) {
    document.getElementById("newsMsg").textContent = "✅ 投稿しました！";
    document.getElementById("newsTitle").value = "";
    document.getElementById("newsBody").value = "";
    document.getElementById("newsImage").value = "";
    document.getElementById("newsImagePreview").style.display = "none";
    loadNews();
  } else {
    document.getElementById("newsMsg").textContent = "❌ パスワードが違います";
  }
});

// Image URL preview
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

// Initial load
checkAuth();
loadBooks();
