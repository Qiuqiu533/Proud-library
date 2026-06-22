/**
 * app.js — プラウド船橋コミュニティ図書館 フロントエンド
 *
 * ## セクション一覧（grep: "===== セクション名"）
 *  Auth             L.6    認証・セッション管理
 *  State            L.303  グローバル状態変数
 *  localStorage     L.360  永続化ヘルパー
 *  Utility          L.524  汎用ユーティリティ（esc, debounce等）
 *  Book card        L.543  書籍カード描画
 *  Pagination       L.652  ページネーション
 *  Load books       L.675  書籍一覧ロード
 *  Modal            L.1382 書籍詳細モーダル
 *  Board            L.2023 理事会パネル（Dashboard/Issues/Stats/Calendar等）
 *  Book Requests    L.3280 リクエスト・ご要望フォーム
 *  クラウド同期     L.3677 お気に入り・読書ログ同期
 *  パスワード変更   L.3830 住民パスワード変更
 *  チャット         L.4259 スレッドチャット
 *  受賞作一覧       L.5009 受賞作タブ（住民向け）
 *  受賞作DB管理     L.5070 受賞作データベース管理（管理者）
 *
 * ## 主要グローバル変数
 *  residentSession  現在ログイン中の住民セッション {room, password}
 *  boardPassword    理事会パスワード（sessionStorage保持）
 *  currentKeyword   蔵書タブの現在の検索キーワード
 *  currentAward     受賞フィルター（空文字=すべて）
 */

// グローバルエラーキャッチャー（デバッグ用）
window.onerror = function(msg, src, line, col, err) {
  console.error('[JS ERROR]', msg, 'at', src, 'line', line);
};

// ===== Auth =====
// residentSession: {room, password} をsessionStorageで保持
let residentSession = null;
try { residentSession = JSON.parse(sessionStorage.getItem("resident_session") || "null"); } catch {}

function validateRoom(room) {
  // 街区形式: 1-5 の街区番号 + ハイフン + 3〜4桁部屋番号
  if (/^[1-5]-\d{3,4}$/.test(room)) return true;
  // 戸建・任意: 6桁数字
  if (/^\d{6}$/.test(room)) return true;
  return false;
}

function showLoginTab(tab) {
  document.getElementById("loginForm").style.display    = tab === "login"    ? "" : "none";
  document.getElementById("registerForm").style.display = tab === "register" ? "" : "none";
  document.getElementById("forgotForm").style.display   = tab === "forgot"   ? "" : "none";
  document.getElementById("tabLogin").classList.toggle("login-tab-active",    tab === "login");
  document.getElementById("tabRegister").classList.toggle("login-tab-active", tab === "register");
}

function _enterApp() {
  document.getElementById("loginScreen").style.display = "none";
  localStorage.setItem("resident_auth", "1");
  _offerMigrateReadingLog();
  setTimeout(checkLoanReminders, 400);
  setTimeout(_updateReqAuthUI, 100);
  loadBooks();
}

async function _offerMigrateReadingLog() {
  if (!residentSession) return;
  const localLogs = getLogEntries();
  if (localLogs.length === 0) return;
  if (localStorage.getItem("reading_log_migrated_" + residentSession.room)) return;
  if (!confirm(`このデバイスに読書記録が${localLogs.length}件あります。\nアカウントに保存しますか？\n（以後は複数端末で同期されます）`)) return;
  const reading_log = {};
  localLogs.forEach(({isbn, status}) => {
    reading_log[isbn] = {status, ...getReadMeta(isbn)};
  });
  const favs = getFavIsbns();
  await fetch("/api/user/sync", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({room: residentSession.room, password: residentSession.password, favorites: favs, reading_log})
  });
  localStorage.setItem("reading_log_migrated_" + residentSession.room, "1");
  alert("読書記録をアカウントに保存しました。");
}

async function checkAuth() {
  const loginScreen = document.getElementById("loginScreen");

  // パスワードリセットリンクの処理
  const urlParams = new URLSearchParams(window.location.search);
  const resetToken = urlParams.get("token");
  if (window.location.pathname === "/reset-password" && resetToken) {
    document.getElementById("loginScreen").style.display = "none";
    document.getElementById("resetPasswordScreen").style.display = "flex";
    window.history.replaceState({}, "", "/");
    document.getElementById("resetSubmitBtn").onclick = async () => {
      const p1 = document.getElementById("resetNewPass").value;
      const p2 = document.getElementById("resetNewPass2").value;
      const err = document.getElementById("resetError");
      if (p1.length < 8) { err.textContent = "8文字以上で入力してください"; return; }
      if (p1 !== p2) { err.textContent = "パスワードが一致しません"; return; }
      const res = await fetch("/api/user/reset-password", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token: resetToken, password: p1})
      });
      const data = await res.json();
      if (res.ok) {
        alert("パスワードを再設定しました。新しいパスワードでログインしてください。");
        document.getElementById("resetPasswordScreen").style.display = "none";
        document.getElementById("loginScreen").style.display = "flex";
        _initLoginQr();
      } else {
        err.textContent = "❌ " + (data.error || "エラーが発生しました");
      }
    };
    return;
  }

  // QRパラメータによる自動ログイン（共通パスワード方式との後方互換）
  const qrPw = urlParams.get("qr");
  if (qrPw) {
    const res = await fetch("/api/auth", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: qrPw})
    });
    if (res.ok) {
      localStorage.setItem("resident_auth", "1");
      window.history.replaceState({}, "", window.location.pathname);
      loginScreen.style.display = "none";
      return;
    }
  }

  // セッション復元
  if (residentSession && residentSession.room) {
    loginScreen.style.display = "none";
    return;
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
  } catch(e) {}
}

function _bindEl(id, ev, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(ev, fn);
}

function _setupRoomAutoHyphen(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("input", () => {
    let v = el.value.replace(/[^\d\-]/g, "");
    if (/^[1-5]\d/.test(v.replace("-", "")) && !v.includes("-")) {
      v = v[0] + "-" + v.slice(1);
    }
    if (v !== el.value) el.value = v;
  });
  el.addEventListener("keydown", e => {
    if (e.key === "Backspace" && el.value.endsWith("-")) {
      e.preventDefault();
      el.value = el.value.slice(0, -1);
    }
  });
}

_setupRoomAutoHyphen("loginRoom");
_setupRoomAutoHyphen("regRoom");
_setupRoomAutoHyphen("forgotRoom");

_bindEl("descTitleSearch", "keydown", e => { if (e.key === "Enter") searchBookForDesc(); });
_bindEl("descIsbn", "keydown", e => { if (e.key === "Enter") lookupBookForDesc(); });

_bindEl("tabLogin",    "click", () => showLoginTab("login"));
_bindEl("tabRegister", "click", () => showLoginTab("register"));
_bindEl("toForgotBtn", "click", () => showLoginTab("forgot"));
_bindEl("toLoginBtn",  "click", () => showLoginTab("login"));

document.getElementById("loginBtn").addEventListener("click", async () => {
  const room = (document.getElementById("loginRoom").value || "").trim();
  const pass = document.getElementById("residentPass").value;
  const err  = document.getElementById("loginError");
  if (!room || !pass) { err.textContent = "部屋番号とパスワードを入力してください"; return; }
  if (!validateRoom(room)) { err.textContent = "部屋番号の形式が正しくありません（例：5-533 または 6桁数字）"; return; }
  err.textContent = "";
  const res = await fetch("/api/user/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({room, password: pass})
  });
  const data = await res.json();
  if (res.ok) {
    residentSession = {room, password: pass};
    sessionStorage.setItem("resident_session", JSON.stringify(residentSession));
    _migrateReadKeysToRoom(room);
    // DBの読書記録をlocalStorageに反映
    if (data.reading_log) {
      Object.entries(data.reading_log).forEach(([isbn, val]) => {
        const status = typeof val === "string" ? val : (val.status || "");
        if (status) setReadStatus(isbn, status);
        if (typeof val === "object") {
          if (val.date) setReadMeta(isbn, val.date, val.review || "", val.due_date || "");
          else if (val.due_date) setDueDate(isbn, val.due_date);
        }
      });
    }
    _enterApp();
    setTimeout(checkLoanReminders, 300);
  } else {
    // 未登録の場合は登録タブへ誘導
    if (res.status === 404) {
      err.textContent = "この部屋番号は未登録です。「新規登録」タブから登録してください。";
    } else {
      err.textContent = "❌ " + (data.error || "ログインできません");
    }
    document.getElementById("residentPass").value = "";
  }
});

document.getElementById("residentPass").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("loginBtn").click();
});

document.getElementById("registerBtn").addEventListener("click", async () => {
  const room  = (document.getElementById("regRoom").value  || "").trim();
  const pass  = document.getElementById("regPass").value;
  const pass2 = document.getElementById("regPass2").value;
  const email      = (document.getElementById("regEmail").value      || "").trim();
  const inviteCode = (document.getElementById("regInviteCode")?.value || "").trim().toUpperCase();
  const err   = document.getElementById("registerError");
  if (!room) { err.textContent = "部屋番号を入力してください"; return; }
  if (!validateRoom(room)) { err.textContent = "部屋番号の形式が正しくありません（例：5-533 または 6桁数字）"; return; }
  if (pass.length < 8) { err.textContent = "パスワードは8文字以上で入力してください"; return; }
  if (pass !== pass2) { err.textContent = "パスワードが一致しません"; return; }
  if (!email || !email.includes("@")) { err.textContent = "メールアドレスを正しく入力してください（返却通知・パスワードリセットに使用します）"; return; }
  err.textContent = "";
  const res = await fetch("/api/user/register", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({room, password: pass, email, invite_code: inviteCode})
  });
  const data = await res.json();
  if (res.ok) {
    residentSession = {room, password: pass};
    sessionStorage.setItem("resident_session", JSON.stringify(residentSession));
    _enterApp();
  } else {
    err.textContent = "❌ " + (data.error || "登録できません");
  }
});

let _forgotResetToken = null;

document.getElementById("forgotBtn").addEventListener("click", async () => {
  const room  = (document.getElementById("forgotRoom").value  || "").trim();
  const email = (document.getElementById("forgotEmail").value || "").trim();
  const msg   = document.getElementById("forgotMsg");
  if (!room || !email) { msg.style.color = "#e05"; msg.textContent = "部屋番号とメールアドレスを入力してください"; return; }
  msg.style.color = "#888"; msg.textContent = "確認中...";
  const res = await fetch("/api/user/forgot-password", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({room, email})
  });
  const data = await res.json();
  if (res.ok && data.token) {
    _forgotResetToken = data.token;
    document.getElementById("forgotStep1").style.display = "none";
    document.getElementById("forgotStep2").style.display = "";
    msg.style.color = "#2a7a2a";
    msg.textContent = "本人確認できました。新しいパスワードを入力してください。";
  } else {
    msg.style.color = "#e05";
    msg.textContent = data.error || "エラーが発生しました";
  }
});

document.getElementById("forgotResetBtn").addEventListener("click", async () => {
  const p1  = (document.getElementById("forgotNewPass").value  || "");
  const p2  = (document.getElementById("forgotNewPass2").value || "");
  const msg = document.getElementById("forgotMsg");
  if (p1.length < 8) { msg.style.color = "#e05"; msg.textContent = "8文字以上で入力してください"; return; }
  if (p1 !== p2)     { msg.style.color = "#e05"; msg.textContent = "パスワードが一致しません"; return; }
  msg.style.color = "#888"; msg.textContent = "設定中...";
  const res = await fetch("/api/user/reset-password", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token: _forgotResetToken, password: p1})
  });
  const data = await res.json();
  if (res.ok) {
    alert("パスワードを再設定しました。新しいパスワードでログインしてください。");
    _forgotResetToken = null;
    document.getElementById("forgotStep1").style.display = "";
    document.getElementById("forgotStep2").style.display = "none";
    document.getElementById("forgotRoom").value = "";
    document.getElementById("forgotEmail").value = "";
    document.getElementById("forgotNewPass").value = "";
    document.getElementById("forgotNewPass2").value = "";
    msg.textContent = "";
    showLoginTab("login");
  } else {
    msg.style.color = "#e05";
    msg.textContent = data.error || "エラーが発生しました";
  }
});

document.getElementById("logoutBtn").addEventListener("click", () => {
  if (!confirm("ログアウトしますか？")) return;
  residentSession = null;
  localStorage.removeItem("resident_auth");
  sessionStorage.removeItem("resident_session");
  sessionStorage.removeItem("resident_pass");
  sessionStorage.removeItem("board_auth");
  sessionStorage.removeItem("board_pass");
  sessionStorage.removeItem("board_name");
  sessionStorage.removeItem("admin_session");
  adminSession = null;
  document.getElementById("loginScreen").style.display = "flex";
  document.getElementById("loginRoom").value = "";
  document.getElementById("residentPass").value = "";
  document.getElementById("loginError").textContent = "";
  showLoginTab("login");
});

// ===== State =====
let currentPage = 1;
let currentKeyword = "";
let currentTotal = 0;
let currentAward = "";   // 受賞フィルター
let currentKana  = "";   // 50音フィルター

// 受賞バッジスタイルマップ
const AWARD_STYLE_MAP = {
  "本屋大賞":         "honmia",
  "本屋大賞ノミネート": "nominee",
  "直木賞":           "naoki",
  "芥川賞":           "akutagawa",
  "山本周五郎賞":     "yamamoto",
  "谷崎潤一郎賞":     "other",
  "三島由紀夫賞":     "other",
  "野間文芸賞":       "other",
  "読売文学賞":       "other",
  "江戸川乱歩賞":     "mystery",
  "日本推理作家協会賞": "mystery",
  "このミステリーがすごい！大賞": "mystery",
  "本格ミステリ大賞": "mystery",
  "日本SF大賞":       "sf",
  "星雲賞":           "sf",
};

function awardStyleClass(awardName) {
  return AWARD_STYLE_MAP[awardName] || "other";
}

function renderAwardBadges(awards) {
  if (!awards || !awards.length) return "";
  // 同じ賞・同じ年の重複を除去（本屋大賞1位とノミネートが混在しないよう）
  const seen = new Set();
  const unique = awards.filter(a => {
    const key = `${a.award}|${a.year}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return `<div class="award-badges">${unique.map(a => {
    const isRank1 = a.rank === 1;
    const cls = isRank1 ? "rank1" : awardStyleClass(a.award);
    const year = a.year ? `'${String(a.year).slice(-2)}` : "";
    const rankLabel = a.rank ? ` ${a.rank}位` : "";
    const crown = isRank1 ? "👑 " : "";
    const label = `${crown}${a.award}${year}${rankLabel}`;
    const tooltip = `${a.award} ${a.year || ""}${rankLabel}`;
    return `<span class="award-badge award-badge--${cls}" title="${tooltip}">${label}</span>`;
  }).join("")}</div>`;
}
let ratingTarget = null;
let ratingScore = 0;
let currentSort = "";
let currentPerPage = parseInt(localStorage.getItem("perPage") || "50");
let logFilter = "all";

// ===== localStorage helpers =====
function getRating(isbn) {
  return { score: 0, votes: 0, reviews: [], my_score: null };
}
async function saveRating(isbn, score, review) {
  const u = residentSession || getCloudUser();
  const body = { isbn, score, review };
  if (u) { body.room = u.room; body.password = u.password || u.pin || ""; }
  const res = await fetch("/api/rate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return await res.json();
}
async function deleteReview(isbn, reviewId) {
  const u = residentSession || getCloudUser();
  if (!u) return null;
  const res = await fetch("/api/rate/review", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ isbn, review_id: reviewId, room: u.room, password: u.password || u.pin || "" })
  });
  return res.ok ? await res.json() : null;
}

function _renderDescSection(isbn, book) {
  if (!book.description) return;
  const placeholder = document.getElementById("modal-desc-placeholder");
  if (!placeholder) return;
  let dateTag = "";
  if (book.manual_review && book.manual_review_date) {
    const d = new Date(book.manual_review_date);
    dateTag = `<span class="manual-review-date">司書登録：${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日</span>`;
  } else if (book.ai_review_date) {
    const ad = new Date(book.ai_review_date);
    const modelName = book.ai_model || "AI";
    dateTag = `<span class="manual-review-date">AI登録：${ad.getFullYear()}年${ad.getMonth()+1}月${ad.getDate()}日（${modelName}）</span>`;
  }
  const aiScoreTag = book.ai_review_score
    ? `<span class="desc-rating">書評品質スコア：${(book.ai_review_score / 10).toFixed(1)} / 5.0</span>` : "";
  const helpfulCount = book.helpful_count || 0;
  const helpfulVoted = (JSON.parse(localStorage.getItem("helpful_voted")||"[]")).includes(isbn);
  const helpfulBtn = `<div class="helpful-row">
    <button class="helpful-btn${helpfulVoted?' voted':''}" onclick="voteHelpful('${isbn}',this)" ${helpfulVoted?'disabled':''}>
      👍 参考になった${helpfulCount > 0 ? `<span class="helpful-count">${helpfulCount}</span>` : ''}
    </button></div>`;
  placeholder.outerHTML = `<div class="modal-section"><h3>📄 内容・収録作品</h3><p class="book-desc">${esc(book.description)}</p>${dateTag}${aiScoreTag}${helpfulBtn}</div>`;
}

async function voteHelpful(isbn, btn) {
  try {
    const res = await fetch("/api/helpful", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isbn })
    });
    const data = await res.json();
    const voted = JSON.parse(localStorage.getItem("helpful_voted") || "[]");
    if (!voted.includes(isbn)) voted.push(isbn);
    localStorage.setItem("helpful_voted", JSON.stringify(voted));
    btn.disabled = true;
    btn.classList.add("voted");
    const count = data.helpful_count || 1;
    btn.innerHTML = `👍 参考になった<span class="helpful-count">${count}</span>`;
  } catch(e) {}
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

function _curRoom() {
  return ((residentSession || getCloudUser()) || {}).room || "";
}
function _readKey(isbn) { const r = _curRoom(); return r ? `read_${r}_${isbn}` : `read_${isbn}`; }
function _metaKey(isbn) { const r = _curRoom(); return r ? `readmeta_${r}_${isbn}` : `readmeta_${isbn}`; }

function getReadStatus(isbn) { return localStorage.getItem(_readKey(isbn)) || ""; }
function setReadStatus(isbn, status) {
  if (status) localStorage.setItem(_readKey(isbn), status);
  else localStorage.removeItem(_readKey(isbn));
  setTimeout(cloudSync, 500);
}
function getLogEntries() {
  const prefix = (() => { const r = _curRoom(); return r ? `read_${r}_` : `read_`; })();
  return Object.keys(localStorage).filter(k => k.startsWith(prefix)).map(k => ({
    isbn: k.slice(prefix.length), status: localStorage[k]
  }));
}
function getReadMeta(isbn) {
  try { return JSON.parse(localStorage.getItem(_metaKey(isbn)) || "{}"); } catch { return {}; }
}
function setReadMeta(isbn, date, memo, due_date) {
  const prev = getReadMeta(isbn);
  const obj = {};
  if (date) obj.date = date;
  if (memo) obj.memo = memo;
  const dd = due_date !== undefined ? due_date : (prev.due_date || "");
  if (dd) obj.due_date = dd;
  if (Object.keys(obj).length) localStorage.setItem(_metaKey(isbn), JSON.stringify(obj));
  else localStorage.removeItem(_metaKey(isbn));
}
function setDueDate(isbn, due_date) {
  const prev = getReadMeta(isbn);
  const obj = { ...prev };
  if (due_date) obj.due_date = due_date;
  else delete obj.due_date;
  if (Object.keys(obj).length) localStorage.setItem(_metaKey(isbn), JSON.stringify(obj));
  else localStorage.removeItem(_metaKey(isbn));
}

function checkLoanReminders() {
  const entries = getLogEntries().filter(e => e.status === "借り中");
  if (!entries.length) { _hideLoanBanner(); return; }
  const today = new Date(); today.setHours(0,0,0,0);
  const overdue = [], soon = [];
  entries.forEach(e => {
    const m = getReadMeta(e.isbn);
    if (!m.due_date) return;
    const due = new Date(m.due_date); due.setHours(0,0,0,0);
    const diff = Math.round((due - today) / 86400000);
    const title = m.title || e.isbn;
    if (diff < 0) overdue.push({ isbn: e.isbn, title, diff });
    else if (diff <= 3) soon.push({ isbn: e.isbn, title, diff });
  });
  if (!overdue.length && !soon.length) { _hideLoanBanner(); return; }
  const lines = [];
  overdue.forEach(b => lines.push(`<span class="loan-item loan-overdue">⚠️ 「${b.title || b.isbn}」が${Math.abs(b.diff)}日超過しています</span>`));
  soon.forEach(b => lines.push(`<span class="loan-item loan-soon">📅 「${b.title || b.isbn}」の返却期限まであと${b.diff}日</span>`));
  const banner = document.getElementById("loanReminderBanner");
  if (banner) { banner.innerHTML = lines.join(""); banner.style.display = "flex"; }
}
function _hideLoanBanner() {
  const b = document.getElementById("loanReminderBanner");
  if (b) b.style.display = "none";
}

// ログイン時に旧キー（部屋番号なし）を新キーへ移行する
function _migrateReadKeysToRoom(room) {
  if (!room || localStorage.getItem(`read_keys_migrated_${room}`)) return;
  Object.keys(localStorage).filter(k => k.startsWith("read_") && !k.startsWith(`read_${room}_`)).forEach(k => {
    const isbn = k.slice(5);
    if (!localStorage.getItem(`read_${room}_${isbn}`)) {
      localStorage.setItem(`read_${room}_${isbn}`, localStorage[k]);
    }
    localStorage.removeItem(k);
  });
  Object.keys(localStorage).filter(k => k.startsWith("readmeta_") && !k.startsWith(`readmeta_${room}_`)).forEach(k => {
    const isbn = k.slice(9);
    if (!localStorage.getItem(`readmeta_${room}_${isbn}`)) {
      localStorage.setItem(`readmeta_${room}_${isbn}`, localStorage[k]);
    }
    localStorage.removeItem(k);
  });
  localStorage.setItem(`read_keys_migrated_${room}`, "1");
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
  const map = { "読んだ": "badge-read", "読書中": "badge-reading", "読みたい": "badge-want", "借り中": "badge-borrowing" };
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
      ${renderAwardBadges(book.awards)}
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
  const ppSel = document.getElementById("perPageSelect");

  let data;
  // キーワードあり・なし共にDB直接（タイトル・著者両方検索対応）
  if (ppSel) { ppSel.disabled = false; ppSel.title = ""; }
  let url = `/api/books/by-genre?keyword=${encodeURIComponent(keyword)}&page=${page}&per=${currentPerPage}`;
  if (currentAward) url += `&award=${encodeURIComponent(currentAward)}`;
  if (currentKana)  url += `&kana_row=${encodeURIComponent(currentKana)}`;
  // 3秒経っても返答がない場合はサーバー起動中メッセージを表示
  const _slowTimer = setTimeout(() => {
    const grid = document.getElementById("bookGrid");
    if (grid && grid.innerHTML.includes("読み込み中")) {
      grid.innerHTML = '<div class="loading">⏳ サーバー起動中です（最大50秒かかる場合があります）<br><small>しばらくそのままお待ちください…</small></div>';
    }
  }, 3000);
  try {
    const res = await fetch(url);
    clearTimeout(_slowTimer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch(e) {
    clearTimeout(_slowTimer);
    const kw = keyword.replace(/'/g, "\\'");
    document.getElementById("bookGrid").innerHTML =
      `<div class="loading-error" style="grid-column:1/-1;width:100%;text-align:center">📡 蔵書の読み込みに失敗しました。<br>通信エラーまたはサーバーの起動中の可能性があります。<br><button class="btn-retry" onclick="loadBooks('${kw}',${page})">再試行する</button></div>`;
    document.getElementById("totalCount").textContent = "";
    return;
  }

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
  if (currentSort === "isbn_desc") books.sort((a, b) => (b.isbn || "").localeCompare(a.isbn || ""));
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
  localStorage.setItem("recent_books", JSON.stringify(recent.slice(0, 30)));
  renderRecentBooks();
}

function renderRecentBooks() {
  let recent = [];
  try { recent = JSON.parse(localStorage.getItem("recent_books") || "[]"); } catch {}
  const section = document.getElementById("recentBooksSection");
  const row = document.getElementById("recentBooksRow");
  if (!section || !row) return;
  // セクション自体は常に表示（ボタンがセクション内にあるため隠すと戻せなくなる）
  section.style.display = "";
  if (!recent.length) {
    row.innerHTML = '<span style="font-size:0.82rem;color:#aaa;padding:4px 0">本をクリックすると履歴が表示されます</span>';
    return;
  }
  row.innerHTML = recent.map(b => {
    const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
    const img = b.cover
      ? `<img src="${b.cover}" alt="${esc(b.title)}" loading="lazy" onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.replaceWith(Object.assign(document.createElement('div'),{className:'mini-card-placeholder',textContent:'📖'}));}">`
      : `<div class="mini-card-placeholder">📖</div>`;
    return `<div class="mini-card" data-isbn="${b.isbn}">
      <div class="mini-card-cover">${img}</div>
      <div class="mini-card-title">${esc(b.title)}</div>
    </div>`;
  }).join("");
  row.querySelectorAll(".mini-card").forEach(el => {
    el.addEventListener("click", () => openModal(el.dataset.isbn));
  });
}

function isSectionVisible(key) {
  return localStorage.getItem(key + "Hidden") !== "1";
}

function toggleSection(key) {
  const visible = !isSectionVisible(key);
  localStorage.setItem(key + "Hidden", visible ? "0" : "1");
  applySectionState(key);
}

function applySectionState(key) {
  const visible = isSectionVisible(key);
  const maps = {
    topNew:  { sectionId: "topNewSection",      rowId: "topNewRow",      btnId: "toggleTopNew",    label: "新着図書" },
    recent:  { sectionId: "recentBooksSection", rowId: "recentBooksRow", btnId: "toggleRecent",    label: "最近見た本" },
    popular: { sectionId: "popularSection",     rowId: "popularRow",     btnId: "togglePopular",   label: "住民に人気の本" },
  };
  const m = maps[key];
  if (!m) return;
  const row  = document.getElementById(m.rowId);
  const btn  = document.getElementById(m.btnId);
  if (row) row.style.display = visible ? "" : "none";
  if (btn) btn.textContent = visible ? `${m.label}を隠す ▲` : `${m.label}を表示 ▼`;
}

function toggleFilterRows() {
  const wrap = document.getElementById("filterRowsWrap");
  const btn  = document.getElementById("toggleFilterRows");
  if (!wrap) return;
  const hidden = wrap.style.display === "none";
  wrap.style.display = hidden ? "" : "none";
  if (btn) btn.textContent = hidden ? "絞り込み ▲" : "絞り込み ▼";
  localStorage.setItem("filterRowsHidden", hidden ? "0" : "1");
}

function applyFilterRowsState() {
  const wrap = document.getElementById("filterRowsWrap");
  const btn  = document.getElementById("toggleFilterRows");
  if (!wrap) return;
  const hidden = localStorage.getItem("filterRowsHidden") === "1";
  wrap.style.display = hidden ? "none" : "";
  if (btn) btn.textContent = hidden ? "絞り込み ▼" : "絞り込み ▲";
}

function applyTopSectionsState() {
  applySectionState("topNew");
  applySectionState("recent");
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
  const ppSel = document.getElementById("perPageSelect");
  if (ppSel) { ppSel.disabled = false; ppSel.title = ""; }
  const res = await fetch(`/api/books/by-genre?genre=${encodeURIComponent(genre)}&page=${page}&per=${currentPerPage}`);
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
  if (currentSort === "isbn_desc") books.sort((a, b) => (b.isbn || "").localeCompare(a.isbn || ""));
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
    const books = (data.books || data);
    if (!books.length) return;
    row.innerHTML = books.map(b => {
      const cover = b.cover || get_cover_url_js(b.isbn);
      const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
      return `<div class="mini-card" data-isbn="${b.isbn}">
        <div class="mini-card-cover">
          <img src="${cover}" alt="${esc(b.title)}" loading="lazy"
            onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.replaceWith(Object.assign(document.createElement('div'),{className:'mini-card-placeholder',textContent:'📖'}));}">
        </div>
        <div class="mini-card-title">${esc(b.title)}</div>
        <div class="mini-card-author">${esc(b.author || "")}</div>
      </div>`;
    }).join("");
    const bookMap = Object.fromEntries(books.map(b => [b.isbn, b]));
    row.querySelectorAll(".mini-card").forEach(el => {
      el.addEventListener("click", () => openModal(el.dataset.isbn, bookMap[el.dataset.isbn]));
    });
    section.style.display = "";
    applySectionState("topNew");
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
  // 新着バッジ: 前回訪問より新しい本の件数を表示
  _updateNewArrivalBadge(data.books);
  localStorage.setItem("lastNewVisit", Date.now());
}

function _updateNewArrivalBadge(books) {
  const badge = document.getElementById("newArrivalBadge");
  if (!badge) return;
  const lastVisit = parseInt(localStorage.getItem("lastNewVisit") || "0");
  if (!lastVisit) { badge.style.display = "none"; return; }
  const newCount = books.filter(b => {
    if (!b.arrived_at) return false;
    return new Date(b.arrived_at).getTime() > lastVisit;
  }).length;
  if (newCount > 0) { badge.textContent = newCount > 9 ? "9+" : newCount; badge.style.display = "inline-flex"; }
  else badge.style.display = "none";
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
function renderLogStats() {
  const statsEl = document.getElementById("logStats");
  if (!statsEl) return;
  const all = getLogEntries();
  const read = all.filter(e => e.status === "読んだ").length;
  const reading = all.filter(e => e.status === "読書中").length;
  const want = all.filter(e => e.status === "読みたい").length;
  const thisMonth = (() => {
    const now = new Date();
    return all.filter(e => {
      if (e.status !== "読んだ") return false;
      const m = getReadMeta(e.isbn);
      if (!m.date) return false;
      const d = new Date(m.date);
      return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
    }).length;
  })();
  if (!all.length) { statsEl.innerHTML = ""; return; }
  statsEl.innerHTML = `
    <div class="log-stat-item"><span class="log-stat-num">${read}</span><span class="log-stat-label">✅ 読んだ</span></div>
    <div class="log-stat-item"><span class="log-stat-num">${reading}</span><span class="log-stat-label">📖 読書中</span></div>
    <div class="log-stat-item"><span class="log-stat-num">${want}</span><span class="log-stat-label">🔖 読みたい</span></div>
    <div class="log-stat-item log-stat-month"><span class="log-stat-num">${thisMonth}</span><span class="log-stat-label">今月読んだ</span></div>
  `;
}

async function loadLog(filter = "all") {
  logFilter = filter;
  renderLogStats();
  document.querySelectorAll(".log-filter-btn").forEach(b => b.classList.toggle("active", b.dataset.status === filter));
  const grid = document.getElementById("logGrid");
  let entries = getLogEntries();
  if (filter !== "all") entries = entries.filter(e => e.status === filter);
  if (!entries.length) { grid.innerHTML = '<div class="loading">記録がありません。<br>本の詳細画面からステータスを設定できます。</div>'; return; }
  grid.innerHTML = '<div class="loading">読み込み中…</div>';
  const statusMap = Object.fromEntries(entries.map(e => [e.isbn, e.status]));
  const res = await fetch(`/api/books/batch?isbns=${entries.map(e => e.isbn).join(",")}`);
  const books = (await res.json()).map(b => ({ ...b, _status: statusMap[b.isbn] }));
  const validBooks = books.filter(Boolean);
  renderGrid("logGrid", validBooks);
  // 日付・感想をカード下に追記
  grid.querySelectorAll(".book-card").forEach(card => {
    const favBtn = card.querySelector(".fav-btn");
    if (!favBtn) return;
    const isbn = favBtn.dataset.isbn;
    if (!isbn) return;
    const meta = getReadMeta(isbn);
    if (!meta.date && !meta.memo) return;
    if (card.querySelector(".log-meta")) return;
    const metaDiv = document.createElement("div");
    metaDiv.className = "log-meta";
    if (meta.date) metaDiv.innerHTML += `<div class="log-meta-date">📅 読んだ日：${meta.date}</div>`;
    if (meta.memo) metaDiv.innerHTML += `<div class="log-meta-memo">✏️ ${esc(meta.memo)}</div>`;
    card.appendChild(metaDiv);
  });
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

// ===== お知らせ既読管理 =====
function getReadNewsIds() {
  try { return new Set(JSON.parse(localStorage.getItem("readNewsIds") || "[]")); } catch { return new Set(); }
}
function markNewsRead(id) {
  const s = getReadNewsIds(); s.add(String(id));
  localStorage.setItem("readNewsIds", JSON.stringify([...s]));
}
function updateNewsBadge(items) {
  const readIds = getReadNewsIds();
  const unread = items.filter(i => !readIds.has(String(i.id))).length;
  const badge = document.getElementById("newsUnreadBadge");
  if (!badge) return;
  if (unread > 0) { badge.textContent = unread > 9 ? "9+" : unread; badge.style.display = "inline-flex"; }
  else badge.style.display = "none";
}

async function loadNews() {
  const list = document.getElementById("newsList");
  if (!list) return;
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch("/api/announcements");
  const items = await res.json();
  if (!items.length) { list.innerHTML = '<div class="loading">お知らせはまだありません。</div>'; return; }
  const readIds = getReadNewsIds();
  list.innerHTML = items.map(item => {
    const isUnread = !readIds.has(String(item.id));
    return `<div class="${isUnread ? 'news-unread' : ''}">${newsItemHtml(item, false)}</div>`;
  }).join("");
  // 表示したら既読にする
  items.forEach(i => markNewsRead(i.id));
  updateNewsBadge([]);
}

async function loadNoBooksReview() {
  const el = document.getElementById("noReviewItems");
  if (!el) return;
  try {
    const res = await fetch("/api/books/no-review");
    const data = await res.json();
    if (!data.books || data.books.length === 0) {
      el.innerHTML = '<span style="color:#4caf50">✅ 書評未登録の本はありません</span>';
      return;
    }
    el.innerHTML = data.books.map(b =>
      `<div style="padding:4px 0;border-bottom:1px solid #ffe082;cursor:pointer;display:flex;align-items:center;gap:8px"
            onclick="document.getElementById('descIsbn').value='${esc(b.isbn)}';lookupBookForDesc()">
        <span style="color:#f57c00;font-size:0.8rem">▶</span>
        <span><b>${esc(b.title)}</b> <span style="color:#888">${esc(b.author||'')}</span></span>
      </div>`
    ).join("") + (data.total > data.books.length
      ? `<div style="color:#888;padding:4px 0;font-size:0.8rem">他 ${data.total - data.books.length} 件...</div>` : "");
  } catch(e) {
    el.innerHTML = '<span style="color:#999">取得できませんでした</span>';
  }
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
      const form = list.querySelector(`[id="news-edit-form-${btn.dataset.id}"]`);
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
  const myRoom = (residentSession || getCloudUser() || {}).room || null;
  const reviewsHtml = rating.reviews && rating.reviews.length
    ? rating.reviews.map(r => {
        const text = typeof r === "string" ? r : (r.text || "");
        const rid  = typeof r === "object" ? (r.id || "") : "";
        const isOwn = myRoom && typeof r === "object" && r.room === myRoom;
        const delBtn = isOwn && rid
          ? `<button class="review-delete-btn" data-isbn="${isbn}" data-rid="${rid}" title="削除">✕</button>`
          : "";
        return `<div class="review-item">${delBtn}💬 ${esc(text)}</div>`;
      }).join("")
    : `<div class="no-content">まだコメントはありません</div>`;
  // 書評・AI登録情報はAPIデータ取得後に確実に描画するため、常にプレースホルダーを使用

  const awardsHtml = book.awards && book.awards.length ? renderAwardBadges(book.awards) : '<div id="modal-awards-placeholder"></div>';
  return `
    <div class="modal-top">
      <div class="modal-cover-wrap">
        <div class="modal-cover">${book.cover ? `<img src="${book.cover}" alt="${esc(book.title)}" onerror="this.parentElement.innerHTML='<div class=\\'modal-cover-placeholder\\'>📖</div>'">` : '<div class="modal-cover-placeholder">📖</div>'}</div>
        <div class="modal-cover-awards">${awardsHtml}</div>
      </div>
      <div class="modal-header">
        <h2>${esc(book.title) || "タイトル不明"}</h2>
        ${infoTable}
        <button class="fav-btn-large ${fav ? 'active' : ''}" data-isbn="${isbn}">
          ${fav ? '❤️ お気に入り済み' : '🤍 お気に入りに追加'}
        </button>
        <button class="wish-btn-large" data-isbn="${isbn}" style="margin-top:6px;width:100%;padding:10px 14px;border-radius:20px;border:1.5px solid #5b8dd9;background:#f0f5ff;color:#3a6aaa;font-size:0.9rem;font-weight:700;cursor:pointer">
          📚 読みたいリストに追加
        </button>
      </div>
    </div>

    <div id="modal-desc-placeholder"></div>

    <div class="modal-section">
      <h3>📚 読書ステータス</h3>
      <div class="read-status-btns">
        ${["読みたい","読書中","読んだ","借り中"].map(s => `
          <button class="read-status-btn ${readStatus === s ? 'active' : ''}" data-status="${s}">${s === "読んだ" ? "✅" : s === "読書中" ? "📖" : s === "借り中" ? "📦" : "🔖"} ${s}</button>
        `).join("")}
        ${readStatus ? `<button class="read-status-btn clear-btn" data-status="">✕ 解除</button>` : ""}
      </div>
      ${readStatus ? (() => { const m = getReadMeta(isbn); return `
      <div class="read-meta-form" id="readMetaForm">
        ${readStatus === "借り中" ? `
        <div class="read-meta-row">
          <label class="read-meta-label">📅 返却予定日</label>
          <input type="date" id="readDueDate" class="read-meta-date" value="${m.due_date || ''}" min="${new Date().toISOString().slice(0,10)}">
        </div>` : `
        <div class="read-meta-row">
          <label class="read-meta-label">📅 読んだ日</label>
          <input type="date" id="readMetaDate" class="read-meta-date" value="${m.date || ''}" max="${new Date().toISOString().slice(0,10)}">
        </div>`}
        <div class="read-meta-row">
          <label class="read-meta-label">✏️ 読書感想</label>
          <textarea id="readMetaMemo" class="read-meta-memo" rows="3" maxlength="300" placeholder="感想を入力（300文字まで）">${esc(m.memo || '')}</textarea>
          <div class="read-meta-count" id="readMetaCount">${(m.memo || '').length}/300文字</div>
        </div>
        <button class="btn-primary read-meta-save" id="readMetaSave">💾 保存</button>
        <span class="read-meta-saved" id="readMetaSaved" style="display:none;color:#2a7;font-size:0.85rem;margin-left:8px">保存しました</span>
      </div>`; })() : ''}
    </div>

    <div class="modal-section">
      <h3>⭐ みんなの評価</h3>
      <div class="big-stars">${rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆"}</div>
      <div class="rating-info">${rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません"}</div>
      ${rating.my_score
        ? `<div class="my-rating-info">あなたの評価：${"★".repeat(rating.my_score)}${"☆".repeat(5 - rating.my_score)}</div>
           <button class="btn-rate btn-rate--rerate" data-isbn="${isbn}">評価を変更する</button>`
        : `<button class="btn-rate" data-isbn="${isbn}">この本を評価する</button>`}
    </div>

    <div class="modal-section">
      <h3>💬 コメント</h3>
      <p style="font-size:0.75rem;color:#aaa;margin-bottom:8px">※ 作品内容の重大なネタバレはご遠慮ください。他の読者が楽しめるよう配慮をお願いします。</p>
      ${reviewsHtml}
    </div>

    <div class="modal-section">
      <h3>🔗 外部リンク・予約</h3>
      <a class="ext-link ext-link-reserve" href="${libUrl}" target="_blank" rel="noopener">🔖 図書館生活で予約・確認</a>
      <div class="external-links" style="margin-top:8px">
        <a class="ext-link ext-link-ndl" href="${ndlUrl}" target="_blank" rel="noopener">国立国会図書館</a>
        <a class="ext-link ext-link-meter" href="${meterUrl}" target="_blank" rel="noopener">読書メーター</a>
        <a class="ext-link ext-link-lib" href="${libUrl}" target="_blank" rel="noopener">図書館生活</a>
      </div>
    </div>

    <div id="modal-related-placeholder"></div>

    <div class="modal-section" id="modal-avail-section">
      <h3>🏛️ 貸出状況</h3>
      <div id="modal-avail-body"><div class="loading" style="font-size:0.85rem;padding:8px 0">取得中…</div></div>
    </div>`;
}

async function _initWishBtn(isbn) {
  const btn = document.querySelector(".wish-btn-large");
  if (!btn) return;
  const u = residentSession || getCloudUser();
  if (!u || !u.room) { btn.style.display = "none"; return; }
  const inList = await isInWishlist(isbn, u.room);
  _setWishBtn(btn, inList);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const cur = btn.classList.contains("active");
    const body = { room: u.room, password: u.password || u.pin || "", isbn };
    await fetch("/api/wishlist", { method: cur ? "DELETE" : "POST",
      headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    _setWishBtn(btn, !cur);
    btn.disabled = false;
    loadWishlistCard();
  });
}
function _setWishBtn(btn, active) {
  btn.classList.toggle("active", active);
  btn.style.background = active ? "#5b8dd9" : "#f0f5ff";
  btn.style.color = active ? "#fff" : "#3a6aaa";
  btn.textContent = active ? "📚 読みたいリスト済み" : "📚 読みたいリストに追加";
}
async function isInWishlist(isbn, room) {
  if (!room) return false;
  try {
    const _wu = residentSession || getCloudUser() || {};
    const res = await fetch(`/api/wishlist?room=${encodeURIComponent(room)}`, { headers: { "X-Password": _wu.password || _wu.pin || "" } });
    if (!res.ok) return false;
    const list = await res.json();
    return Array.isArray(list) && list.some(w => w.isbn === isbn);
  } catch { return false; }
}
async function toggleWishNotify(isbn, btn) {
  const u = residentSession || getCloudUser();
  if (!u) return;
  const currentOn = btn.dataset.notify === "1";
  const newOn = !currentOn;
  try {
    const res = await fetch("/api/wishlist/notify", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room: u.room, password: u.password || u.pin || "", isbn, notify: newOn }),
    });
    if (!res.ok) return;
    btn.dataset.notify = newOn ? "1" : "0";
    btn.title = newOn ? "通知ON（タップでOFF）" : "通知OFF（タップでON）";
    btn.style.background = newOn ? "#e8f5e9" : "#f5f5f5";
    btn.style.color = newOn ? "#2e7d32" : "#999";
    btn.style.borderColor = "#ddd";
    btn.textContent = newOn ? "🔔 返却通知ON" : "🔕 通知OFF";
  } catch (e) {}
}

async function loadWishlistCard() {
  const sec  = document.getElementById("wishlistSection");
  const grid = document.getElementById("wishlistGrid");
  if (!sec || !grid) return;
  const u = residentSession || getCloudUser();
  if (!u || !u.room) { sec.style.display = "none"; return; }
  const res = await fetch(`/api/wishlist?room=${encodeURIComponent(u.room)}`, { headers: { "X-Password": u.password || u.pin || "" } }).catch(() => null);
  if (!res || !res.ok) { sec.style.display = "none"; return; }
  const list = await res.json();
  if (!list.length) { sec.style.display = "none"; return; }
  sec.style.display = "";
  const isbns = list.map(w => w.isbn);
  const bRes = await fetch("/api/books/batch", { method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({isbns}) });
  const books = bRes.ok ? await bRes.json() : [];
  const bookMap = Object.fromEntries(books.map(b => [b.isbn, b]));
  const notifyMap = Object.fromEntries(list.map(w => [w.isbn, w.notify !== false]));
  grid.innerHTML = isbns.map(isbn => {
    const b = bookMap[isbn] || { isbn, title: isbn };
    const ndl = `https://ndlsearch.ndl.go.jp/thumbnail/${isbn}.jpg`;
    const notifyOn = notifyMap[isbn];
    return `<div class="mini-card" data-isbn="${isbn}">
      <div onclick="openModal('${isbn}')" style="cursor:pointer">
        <img src="${b.cover || ndl}" alt="${esc(b.title)}" loading="lazy"
          onerror="if(this.src!=='${ndl}')this.src='${ndl}';else this.style.display='none';">
        <div class="mini-title">${esc(b.title)}</div>
      </div>
      <button onclick="toggleWishNotify('${isbn}', this)"
        data-notify="${notifyOn ? '1' : '0'}"
        title="${notifyOn ? '通知ON（タップでOFF）' : '通知OFF（タップでON）'}"
        style="margin-top:4px;width:100%;font-size:0.72rem;padding:3px 0;border:1px solid #ddd;border-radius:6px;background:${notifyOn ? '#e8f5e9' : '#f5f5f5'};color:${notifyOn ? '#2e7d32' : '#999'};cursor:pointer">
        ${notifyOn ? '🔔 返却通知ON' : '🔕 通知OFF'}
      </button>
    </div>`;
  }).join("");
}

function _bindModalEvents(isbn) {
  document.querySelector(".fav-btn-large").addEventListener("click", e => {
    toggleFav(isbn);
    const active = isFav(isbn);
    e.currentTarget.classList.toggle("active", active);
    e.currentTarget.textContent = active ? "❤️ お気に入り済み" : "🤍 お気に入りに追加";
  });
  _initWishBtn(isbn);
  document.querySelectorAll(".read-status-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      setReadStatus(isbn, btn.dataset.status);
      openModal(isbn);
    });
  });
  const memoEl = document.getElementById("readMetaMemo");
  const countEl = document.getElementById("readMetaCount");
  const saveBtn = document.getElementById("readMetaSave");
  if (memoEl && countEl) {
    memoEl.addEventListener("input", () => { countEl.textContent = memoEl.value.length + "/300文字"; });
  }
  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      const date = (document.getElementById("readMetaDate") || {}).value || "";
      const due_date = (document.getElementById("readDueDate") || {}).value || "";
      const memo = memoEl ? memoEl.value : "";
      setReadMeta(isbn, date, memo, due_date || undefined);
      if (due_date) setDueDate(isbn, due_date);
      checkLoanReminders();
      const saved = document.getElementById("readMetaSaved");
      if (saved) { saved.style.display = "inline"; setTimeout(() => { saved.style.display = "none"; }, 2000); }
    });
  }
  const rateBtn = document.querySelector(".btn-rate");
  if (rateBtn) rateBtn.addEventListener("click", () => {
    ratingTarget = isbn;
    openRateModal();
  });
  const rerateBtn = document.querySelector(".btn-rate--rerate");
  if (rerateBtn) rerateBtn.addEventListener("click", () => {
    ratingTarget = isbn;
    openRateModal();
  });
  // コメント削除ボタン
  document.querySelectorAll(".review-delete-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("このコメントを削除しますか？")) return;
      btn.disabled = true;
      const data = await deleteReview(btn.dataset.isbn, btn.dataset.rid);
      if (data) {
        _updateReviewsSection(isbn, data);
      } else {
        alert("削除できませんでした");
        btn.disabled = false;
      }
    });
  });
}

function _updateReviewsSection(isbn, rating) {
  const myRoom = (residentSession || getCloudUser() || {}).room || null;
  const reviewsHtml = rating.reviews && rating.reviews.length
    ? rating.reviews.map(r => {
        const text = typeof r === "string" ? r : (r.text || "");
        const rid  = typeof r === "object" ? (r.id || "") : "";
        const isOwn = myRoom && typeof r === "object" && r.room === myRoom;
        const delBtn = isOwn && rid
          ? `<button class="review-delete-btn" data-isbn="${isbn}" data-rid="${rid}" title="削除">✕</button>`
          : "";
        return `<div class="review-item">${delBtn}💬 ${esc(text)}</div>`;
      }).join("")
    : `<div class="no-content">まだコメントはありません</div>`;
  const section = Array.from(document.querySelectorAll(".modal-section"))
    .find(el => el.querySelector("h3")?.textContent.includes("コメント"));
  if (section) {
    section.querySelectorAll(".review-item, .no-content").forEach(el => el.remove());
    section.insertAdjacentHTML("beforeend", reviewsHtml);
    // 新しい削除ボタンに再バインド
    section.querySelectorAll(".review-delete-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("このコメントを削除しますか？")) return;
        btn.disabled = true;
        const data = await deleteReview(btn.dataset.isbn, btn.dataset.rid);
        if (data) _updateReviewsSection(isbn, data);
        else { alert("削除できませんでした"); btn.disabled = false; }
      });
    });
  }
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
      const titleHint = encodeURIComponent(preloadedBook.title || "");
      const _room = (residentSession || getCloudUser() || {}).room || "";
      const _roomParam = _room ? `&room=${encodeURIComponent(_room)}` : "";
      const res = await fetch(`/api/book/${isbn}?title=${titleHint}${_roomParam}`);
      const book = await res.json();
      const availEl = document.getElementById("modal-avail-body");
      if (availEl) {
        const availHtml = book.availability && book.availability.length
          ? book.availability.map(a => {
              const isProud = a.library && a.library.includes("プラウド");
              return `<div class="avail-row${isProud ? " avail-row--proud" : ""}"><span>${a.library}</span>${statusBadge(a.status)}</div>`;
            }).join("")
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
      // 評価・コメントをサーバーデータで更新
      const rating = book.rating || { score: 0, votes: 0, reviews: [] };
      const starsEl = document.querySelector(".big-stars");
      const ratingInfoEl = document.querySelector(".rating-info");
      if (starsEl) starsEl.textContent = rating.score ? "★".repeat(Math.round(rating.score)) + "☆".repeat(5 - Math.round(rating.score)) : "☆☆☆☆☆";
      if (ratingInfoEl) ratingInfoEl.textContent = rating.score ? `${rating.score.toFixed(1)} / 5.0（${rating.votes}件）` : "まだ評価がありません";
      // コメントセクションも更新（初期描画では空で表示されているため）
      _updateReviewsSection(isbn, rating);
      // 内容紹介・AI登録情報・参考ボタンを描画
      _renderDescSection(isbn, book);
    } catch(e) {
      const availEl = document.getElementById("modal-avail-body");
      if (availEl) availEl.innerHTML = `<div class="avail-row"><span>取得できませんでした</span></div>`;
    } finally {
      _loadRelatedBooks(isbn);
    }
  } else {
    // preloadedBookなし（評価後の再表示など）：全データ取得してから表示
    document.getElementById("modalContent").innerHTML = '<div class="loading">読み込み中…</div>';
    try {
      const _room2 = (residentSession || getCloudUser() || {}).room || "";
      const _roomParam2 = _room2 ? `?room=${encodeURIComponent(_room2)}` : "";
      const res = await fetch(`/api/book/${isbn}${_roomParam2}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const book = await res.json();
      const rating = book.rating || { score: 0, votes: 0, reviews: [] };
      const availHtml = book.availability && book.availability.length
        ? book.availability.map(a => {
            const isProud = a.library && a.library.includes("プラウド");
            return `<div class="avail-row${isProud ? " avail-row--proud" : ""}"><span>${a.library}</span>${statusBadge(a.status)}</div>`;
          }).join("")
        : `<div class="avail-row"><span>情報なし</span></div>`;
      const html = _renderModalContent(isbn, book, rating);
      document.getElementById("modalContent").innerHTML = html;
      document.getElementById("modal-avail-body").innerHTML = availHtml;
      _bindModalEvents(isbn);
      _renderDescSection(isbn, book);
      _loadRelatedBooks(isbn);
    } catch(e) {
      document.getElementById("modalContent").innerHTML =
        `<div class="loading-error" style="text-align:center;padding:40px 20px;color:#c00;line-height:2">📡 書籍情報の取得に失敗しました。<br>通信エラーまたはサーバーの起動中の可能性があります。<br><button class="btn-retry" onclick="openModal('${isbn.replace(/'/g,"\\'")}')">再試行する</button></div>`;
    }
  }
}

async function _loadRelatedBooks(isbn) {
  const placeholder = document.getElementById("modal-related-placeholder");
  if (!placeholder) return;
  // このモーダルがどのISBN用かをマーク（非同期完了時に照合する）
  placeholder.dataset.isbn = isbn;
  try {
    const res = await fetch(`/api/books/related/${isbn}`);
    const data = await res.json();
    // fetch完了後、別の本のモーダルに切り替わっていたら描画しない
    const current = document.getElementById("modal-related-placeholder");
    if (!current || current.dataset.isbn !== isbn) return;
    const renderCarousel = (books, label) => {
      if (!books || books.length === 0) return "";
      const items = books.map(b => {
        const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
        const imgOrPlaceholder = `<img src="${b.cover || ndlFallback}" alt="${esc(b.title)}" loading="lazy"
          onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.replaceWith(Object.assign(document.createElement('div'),{className:'related-thumb-placeholder',textContent:'📖'}));}">`;
        return `<div class="related-card" onclick="openModal('${b.isbn}')" onkeydown="if(event.key==='Enter'||event.key===' ')openModal('${b.isbn}')" role="button" tabindex="0">
          <div class="related-thumb">${imgOrPlaceholder}</div>
          <div class="related-title">${esc(b.title)}</div>
          <div class="related-author">${esc(b.author || "")}</div>
        </div>`;
      }).join("");
      return `<div class="modal-section">
        <h3>${label}</h3>
        <div class="related-carousel">${items}</div>
      </div>`;
    };
    const html = renderCarousel(data.same_author, "👤 同じ著者の本") + renderCarousel(data.same_genre, "📚 同じジャンルの本");
    if (html) current.outerHTML = html;
  } catch(e) {}
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

function switchToBooksAndSearch(keyword) {
  // 蔵書タブが非アクティブなら切り替えてから検索
  const booksBtn = document.querySelector('.tab-btn[data-tab="books"]');
  if (booksBtn && !booksBtn.classList.contains("active")) {
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    booksBtn.classList.add("active");
    booksBtn.setAttribute("aria-selected", "true");
    document.getElementById("tab-books").classList.add("active");
  }
  loadBooks(keyword);
}

// ===== Events =====
document.getElementById("searchBtn").addEventListener("click", () => switchToBooksAndSearch(document.getElementById("searchInput").value));
document.getElementById("searchInput").addEventListener("keydown", e => { if (e.key === "Enter") switchToBooksAndSearch(document.getElementById("searchInput").value); });
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

document.getElementById("perPageSelect").addEventListener("change", e => {
  currentPerPage = parseInt(e.target.value);
  localStorage.setItem("perPage", currentPerPage);
  if (currentGenre) loadBooksByGenre(currentGenre, 1);
  else loadBooks(currentKeyword, 1);
});

// 受賞フィルターピル
document.querySelectorAll(".award-pill").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".award-pill").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentAward = btn.dataset.award || "";
    currentGenre = "";
    loadBooks(currentKeyword, 1);
  });
});

document.querySelectorAll(".kana-pill").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".kana-pill").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentKana = btn.dataset.kana || "";
    currentPage = 1;
    // 50音フィルター選択時はキーワード検索をクリア（AND検索で0件になるため）
    currentKeyword = "";
    const si = document.getElementById("searchInput");
    if (si) si.value = "";
    loadBooks("", 1);
  });
});

// perPageSelectの初期値をlocalStorageから復元
(function() {
  const sel = document.getElementById("perPageSelect");
  if (sel) sel.value = String(currentPerPage);
})();

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
    if (btn.dataset.tab === "card") { loadCard(); loadWishlistCard(); }
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

// 管理者 fetch ヘルパー: X-Password ヘッダーを自動付与（ボディ内 password も後方互換で残す）
function adminFetch(url, opts = {}) {
  const headers = {"Content-Type": "application/json", "X-Password": boardPassword, ...(opts.headers || {})};
  return fetch(url, {...opts, headers});
}

// 個人認証セッション
let adminSession = JSON.parse(sessionStorage.getItem("admin_session") || "null");
// adminSession = {code, name, role} or null

let boardSenderName = (adminSession && adminSession.name) || sessionStorage.getItem("board_name") || "";

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
  if (adminSession) {
    openBoardPanel();
  } else {
    document.getElementById("boardLoginModal").style.display = "flex";
    const codeEl = document.getElementById("boardCode");
    if (codeEl) codeEl.focus();
    else document.getElementById("boardPass").focus();
  }
});

document.getElementById("boardLoginClose").addEventListener("click", () => {
  document.getElementById("boardLoginModal").style.display = "none";
});

document.getElementById("boardLoginBtn").addEventListener("click", async () => {
  const codeEl = document.getElementById("boardCode");
  const code = codeEl ? codeEl.value.trim() : "";
  const pass = document.getElementById("boardPass").value;
  const err = document.getElementById("boardLoginError");
  if (!code) { err.textContent = "管理者コードを入力してください"; codeEl && codeEl.focus(); return; }
  if (!pass) { err.textContent = "パスワードを入力してください"; return; }
  err.textContent = "認証中…";
  const res = await fetch("/api/admin/login", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({code, password: pass})
  });
  const data = await res.json();
  if (res.ok && data.ok) {
    adminSession = {code: data.code, name: data.name, role: data.role};
    boardPassword = pass;
    boardSenderName = data.name;
    sessionStorage.setItem("admin_session", JSON.stringify(adminSession));
    sessionStorage.setItem("board_auth", "1");
    sessionStorage.setItem("board_pass", pass);
    sessionStorage.setItem("board_name", data.name);
    document.getElementById("boardLoginModal").style.display = "none";
    document.getElementById("boardPass").value = "";
    if (codeEl) codeEl.value = "";
    err.textContent = "";
    openBoardPanel();
  } else {
    err.textContent = "❌ " + (data.error || "認証に失敗しました");
    document.getElementById("boardPass").value = "";
  }
});
document.getElementById("boardPass").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("boardLoginBtn").click();
});
document.getElementById("boardCode") && document.getElementById("boardCode").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("boardPass").focus();
});

document.getElementById("boardClose").addEventListener("click", () => {
  document.getElementById("boardPanel").style.display = "none";
  document.body.style.overflow = "";
  if (reqPollTimer) { clearInterval(reqPollTimer); reqPollTimer = null; }
  lastSeenReqPending = null;
  lastSeenChatId = null;
});

document.getElementById("boardAdminLogout")?.addEventListener("click", () => {
  if (!confirm("管理者メニューからログアウトしますか？")) return;
  adminSession = null;
  boardPassword = "";
  boardSenderName = "";
  sessionStorage.removeItem("admin_session");
  sessionStorage.removeItem("board_auth");
  sessionStorage.removeItem("board_pass");
  sessionStorage.removeItem("board_name");
  document.getElementById("boardPanel").style.display = "none";
  document.body.style.overflow = "";
  if (reqPollTimer) { clearInterval(reqPollTimer); reqPollTimer = null; }
});

const MASTER_ONLY_TABS = ["settings", "adminusers"];

function applyRoleTabVisibility() {
  const isMaster = adminSession && adminSession.role === "master";
  MASTER_ONLY_TABS.forEach(key => {
    const btn = document.querySelector(`.board-tab[data-btab="${key}"]`);
    if (btn) btn.style.display = isMaster ? "" : "none";
  });
  // ヘッダーにログイン者名・ロール表示
  const headerEl = document.getElementById("boardUserLabel");
  if (headerEl && adminSession) {
    const roleLabel = adminSession.role === "master" ? "マスター" : "管理者";
    headerEl.textContent = `👤 ${adminSession.name}（${roleLabel}）`;
  }
}

function openBoardPanel() {
  adminSession = JSON.parse(sessionStorage.getItem("admin_session") || "null");
  boardPassword = sessionStorage.getItem("board_pass") || "";
  boardSenderName = sessionStorage.getItem("board_name") || "";
  reqAdminPass = boardPassword;
  const lbl = document.getElementById("chatSenderLabel");
  if (lbl) lbl.textContent = boardSenderName ? `👤 ${boardSenderName}` : "";
  document.getElementById("boardPanel").style.display = "flex";
  document.body.style.overflow = "hidden";
  applyRoleTabVisibility();
  // デフォルトタブを「ダッシュボード」に設定
  document.querySelectorAll(".board-tab").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".board-tab-panel").forEach(p => p.classList.remove("active"));
  const dashTab = document.querySelector('.board-tab[data-btab="dashboard"]');
  const dashPanel = document.getElementById("btab-dashboard");
  if (dashTab) dashTab.classList.add("active");
  if (dashPanel) dashPanel.classList.add("active");
  loadDashboard();
}

// Board tabs
document.querySelectorAll(".board-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".board-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".board-tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("btab-" + btn.dataset.btab).classList.add("active");
    if (btn.dataset.btab === "dashboard") loadDashboard();
    if (btn.dataset.btab === "adminnews") loadAdminNews();
    if (btn.dataset.btab === "newarrival") loadNewArrivalAdmin();
    if (btn.dataset.btab === "analytics") loadOpsStats();
    if (btn.dataset.btab === "calendar") loadCalendar();
    if (btn.dataset.btab === "libschedule") loadLibSchedule();
    if (btn.dataset.btab === "issues") loadIssues();
    if (btn.dataset.btab === "brequest") loadReqManage();
    if (btn.dataset.btab === "loaned") loadLoanedBooks();
    if (btn.dataset.btab === "staffchat") initStaffChat();
    if (btn.dataset.btab === "settings") loadAdminQr();
    if (btn.dataset.btab === "adminusers") loadAdminUsers();
    if (btn.dataset.btab === "collections") loadAdminCollections();
    if (btn.dataset.btab === "bookdesc") {
      document.getElementById("descIsbn").value = "";
      document.getElementById("descText").value = "";
      document.getElementById("descCount").textContent = "（0/600文字）";
      document.getElementById("descBookInfo").style.display = "none";
      document.getElementById("descMsg").textContent = "";
      const b1 = document.getElementById("descAwardBadges"); if (b1) b1.innerHTML = "";
      loadNoBooksReview();
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

  // ISBN一括インポート
  document.getElementById("bulkImportBtn")?.addEventListener("click", async () => {
    const raw = (document.getElementById("bulkIsbnInput")?.value || "").trim();
    const arrived_at = document.getElementById("bulkArrivalDate")?.value;
    const prog = document.getElementById("bulkImportProgress");
    if (!raw) { if (prog) prog.innerHTML = '<span style="color:#e05">ISBNを入力してください</span>'; return; }
    if (!arrived_at) { if (prog) prog.innerHTML = '<span style="color:#e05">入荷日を入力してください</span>'; return; }
    const isbns = raw.split("\n").map(s => s.trim().replace(/-/g, "")).filter(s => /^\d{10,13}$/.test(s)).slice(0, 50);
    if (!isbns.length) { if (prog) prog.innerHTML = '<span style="color:#e05">有効なISBNが見つかりません（10桁または13桁の数字）</span>'; return; }
    if (prog) prog.innerHTML = `<span style="color:#555">0/${isbns.length}件処理中…</span>`;
    let ok = 0, fail = 0;
    for (let i = 0; i < isbns.length; i++) {
      const isbn = isbns[i];
      if (prog) prog.innerHTML = `<span style="color:#555">${i + 1}/${isbns.length}件処理中… (✅${ok} ❌${fail})</span>`;
      try {
        const res = await fetch("/api/new-arrivals", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({password: boardPassword, isbn, arrived_at, title: "", author: "", publisher: "", cover: ""})
        });
        if (res.ok) ok++; else fail++;
      } catch { fail++; }
      await new Promise(r => setTimeout(r, 200)); // API負荷軽減
    }
    if (prog) prog.innerHTML = `<span style="color:#3d6b4f">✅ 完了：${ok}件登録、${fail}件失敗</span>`;
    document.getElementById("bulkIsbnInput").value = "";
    loadNewArrivalAdmin();
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

// ===== Dashboard =====
async function loadDashboard() {
  const el = document.getElementById("dashboardContent");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';

  const pw = boardPassword;
  try {
    const [dashRes, awardsRes] = await Promise.all([
      fetch(`/api/admin/dashboard-data`, { headers: { "X-Password": pw } }),
      fetch(`/api/award-books/awards`),
    ]);
    if (!dashRes.ok) throw new Error("dashboard-data fetch failed");
    const d = await dashRes.json();
    const awardsData = awardsRes.ok ? await awardsRes.json() : [];
    const awardCount = awardsData.reduce((s, a) => s + (a.count || 0), 0);

    const reqs   = d.requests  || [];
    const issues = d.issues    || [];
    const sched  = d.schedule  || [];
    // 集計
    const pendingReqs     = reqs.filter(r => r.type !== "feedback" && r.status === "pending");
    const pendingFeedback = reqs.filter(r => r.type === "feedback" && (r.status === "pending" || r.status === "fb_received"));
    const openIssues      = issues.filter(i => i.status !== "解決済み");
    const newArrivalList  = {length: d.new_arrivals_count || 0};
    const totalBooks      = d.total_books || 0;

    // stats画面のリアルタイム数値を更新
    const stEl = document.getElementById("statTotalBooks");
    if (stEl) stEl.textContent = totalBooks.toLocaleString();
    const saEl = document.getElementById("statAwardCount");
    if (saEl) saEl.textContent = awardCount.toLocaleString();

    // DB使用量
    let dbPct = null, dbMB = null, dbLimitMB = 512;
    if (d.db_total_mb != null) {
      dbMB  = d.db_total_mb.toFixed(1);
      dbPct = Math.round(d.db_total_mb / dbLimitMB * 100);
    }
    const dbBarColor = dbPct >= 90 ? "#e05" : dbPct >= 70 ? "#f0a500" : "#3d6b4f";

    // 直近の予定（今日以降 3件）
    const today = new Date().toISOString().slice(0, 10);
    const upcomingSched = sched
      .filter(s => s.event_date >= today)
      .sort((a, b) => a.event_date.localeCompare(b.event_date))
      .slice(0, 4);

    // 最新リクエスト 3件
    const latestReqs = [...reqs].sort((a, b) => b.id - a.id).slice(0, 4);
    // 未対応課題 3件
    const latestIssues = openIssues.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)).slice(0, 4);

    const alertLevel = (n) => n > 0 ? "dash-alert-red" : "dash-alert-green";
    const alertIcon  = (n) => n > 0 ? "🔴" : "✅";

    el.innerHTML = `
      <div class="dash-updated">最終更新: ${new Date().toLocaleString("ja-JP", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</div>

      <!-- 要対応バナー -->
      ${(pendingReqs.length + pendingFeedback.length + openIssues.length) > 0 ? `
      <div class="dash-banner dash-banner-warn">
        ⚠️ 要対応の項目があります — リクエスト未対応 <strong>${pendingReqs.length}</strong>件、意見・要望 <strong>${pendingFeedback.length}</strong>件、未解決課題 <strong>${openIssues.length}</strong>件
      </div>` : `
      <div class="dash-banner dash-banner-ok">
        ✅ 要対応の項目はありません
      </div>`}

      <!-- 要対応カード -->
      <div class="dash-section-title">🔴 要対応</div>
      <div class="dash-card-row">
        <div class="dash-card ${alertLevel(pendingReqs.length)} dash-clickable" onclick="switchBoardTab('brequest')">
          <div class="dash-card-num">${pendingReqs.length}</div>
          <div class="dash-card-label">未対応<br>本のリクエスト</div>
          <div class="dash-card-action">確認 →</div>
        </div>
        <div class="dash-card ${alertLevel(pendingFeedback.length)} dash-clickable" onclick="switchBoardTabFeedback()">
          <div class="dash-card-num">${pendingFeedback.length}</div>
          <div class="dash-card-label">未対応<br>意見・要望</div>
          <div class="dash-card-action">確認 →</div>
        </div>
        <div class="dash-card ${alertLevel(openIssues.length)} dash-clickable" onclick="switchBoardTab('issues')">
          <div class="dash-card-num">${openIssues.length}</div>
          <div class="dash-card-label">未解決<br>課題</div>
          <div class="dash-card-action">確認 →</div>
        </div>
      </div>

      <!-- 蔵書サマリー -->
      <div class="dash-section-title">📚 蔵書サマリー</div>
      <div class="dash-card-row">
        <div class="dash-card dash-card-blue">
          <div class="dash-card-num">${totalBooks.toLocaleString()}</div>
          <div class="dash-card-label">総蔵書数（DB登録）</div>
        </div>
        <div class="dash-card dash-card-gold dash-clickable" onclick="switchBoardTab('awarddb')">
          <div class="dash-card-num">${awardCount}</div>
          <div class="dash-card-label">受賞・ノミネート作品</div>
          <div class="dash-card-action">詳細 →</div>
        </div>
        <div class="dash-card dash-card-teal dash-clickable" onclick="switchBoardTab('newarrival')">
          <div class="dash-card-num">${newArrivalList.length}</div>
          <div class="dash-card-label">新着登録済み</div>
          <div class="dash-card-action">管理 →</div>
        </div>
      </div>

      <!-- DB使用量 -->
      <div class="dash-section-title">🗄️ DB使用量（Neon 無料枠 512MB）</div>
      <div class="dash-db-bar-wrap">
        ${dbPct !== null ? `
        <div class="dash-db-bar-track">
          <div class="dash-db-bar-fill" style="width:${dbPct}%;background:${dbBarColor}"></div>
        </div>
        <div class="dash-db-bar-label">
          <span>${dbMB} MB 使用 / 512 MB</span>
          <span style="color:${dbBarColor};font-weight:700">${dbPct}%</span>
          ${dbPct >= 90 ? '<span style="color:#e05;font-weight:700">⚠️ 残り僅か！画像削除を検討してください</span>' : ""}
        </div>` : `<span style="color:#aaa;font-size:0.85rem">取得できませんでした</span>`}
      </div>

      <!-- 直近のイベント・休館 -->
      <div class="dash-section-title">📅 直近のイベント・休館日
        <button class="dash-more-btn" onclick="switchBoardTab('libschedule')">すべて見る →</button>
      </div>
      ${upcomingSched.length ? `
      <div class="dash-list">
        ${upcomingSched.map(s => {
          const isClose = s.event_date <= new Date(Date.now()+3*86400000).toISOString().slice(0,10);
          const typeLabel = s.type === "closed" ? "🚫 臨時休館" : "📅 イベント";
          return `<div class="dash-list-item${isClose?" dash-list-urgent":""}">
            <span class="dash-list-date">${s.event_date}</span>
            <span class="dash-list-badge${s.type==="closed"?" dash-badge-closed":""}">${typeLabel}</span>
            <span class="dash-list-text">${esc(s.title)}</span>
          </div>`;
        }).join("")}
      </div>` : `<div class="dash-empty">直近の予定はありません</div>`}

      <!-- 最新リクエスト -->
      <div class="dash-section-title">📬 最新リクエスト
        <button class="dash-more-btn" onclick="switchBoardTab('brequest')">すべて見る →</button>
      </div>
      ${latestReqs.length ? `
      <div class="dash-list">
        ${latestReqs.map(r => {
          const statusCls = r.status === "pending" || r.status === "fb_received" ? " dash-list-urgent" : "";
          const _fbStatusMap = { pending:"🔴 未対応", approved:"✅ 承認", rejected:"❌ 見送り", done:"📦 入荷済", fb_received:"📬 受付中", fb_checking:"🔍 確認中", fb_done:"✅ 対応済", fb_rejected:"❌ 見送り", fb_pending:"⏳ 検討中", fb_noted:"📝 参考意見", fb_none:"➖ 対応なし" };
          const statusLabel = _fbStatusMap[r.status] || r.status;
          const typeLabel = r.type === "feedback" ? "💬 意見" : "📖 リクエスト";
          return `<div class="dash-list-item${statusCls}">
            <span class="dash-list-badge">${typeLabel}</span>
            <span class="dash-list-text">${esc(r.title || r.body || "")}</span>
            <span class="dash-list-status">${statusLabel}</span>
          </div>`;
        }).join("")}
      </div>` : `<div class="dash-empty">リクエストはありません</div>`}

      <!-- 未解決課題 -->
      <div class="dash-section-title">📋 未解決課題
        <button class="dash-more-btn" onclick="switchBoardTab('issues')">すべて見る →</button>
      </div>
      ${latestIssues.length ? `
      <div class="dash-list">
        ${latestIssues.map(i => {
          const pCls = i.priority === "高" ? " dash-list-urgent" : "";
          const pLabel = i.priority === "高" ? "🔴 高" : i.priority === "中" ? "🟡 中" : "🟢 低";
          return `<div class="dash-list-item${pCls}">
            <span class="dash-list-badge">${pLabel}</span>
            <span class="dash-list-text">${esc(i.title)}</span>
            <span class="dash-list-status" style="color:#888;font-size:0.78rem">${i.status}</span>
          </div>`;
        }).join("")}
      </div>` : `<div class="dash-empty">✅ 未解決の課題はありません</div>`}

      <!-- クイックアクション -->
      <div class="dash-section-title">⚡ クイックアクション</div>
      <div class="dash-quick-row">
        <button class="dash-quick-btn" onclick="switchBoardTab('adminnews')">📢 お知らせを投稿</button>
        <button class="dash-quick-btn" onclick="switchBoardTab('newarrival')">📥 新着本を登録</button>
        <button class="dash-quick-btn" onclick="switchBoardTab('bookdesc')">📝 書評を入力</button>
        <button class="dash-quick-btn" onclick="switchBoardTab('issues')">📋 課題を追加</button>
        <button class="dash-quick-btn" onclick="switchBoardTab('staffchat')">💬 チャットを開く</button>
        <button class="dash-quick-btn" onclick="switchBoardTab('settings')">⚙️ 設定</button>
      </div>
    `;

    // analyticsサブタブのイベント設定（初回のみ）
    _initAnalyticsSubTabs();

  } catch(e) {
    el.innerHTML = `<div style="color:#e05;padding:20px">読み込みエラー: ${e.message}</div>`;
    console.error("loadDashboard error", e);
  }
}

function switchBoardTabFeedback() {
  switchBoardTab("brequest");
  // 少し遅らせてフィードバックサブタブをアクティブにする
  setTimeout(() => {
    const fbBtn = document.querySelector('#btab-brequest .req-subtab-btn[data-subtab="feedback"]');
    if (fbBtn) fbBtn.click();
  }, 50);
}

function switchBoardTab(tabKey) {
  document.querySelectorAll(".board-tab").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".board-tab-panel").forEach(p => p.classList.remove("active"));
  const btn = document.querySelector(`.board-tab[data-btab="${tabKey}"]`);
  const panel = document.getElementById(`btab-${tabKey}`);
  if (btn) btn.classList.add("active");
  if (panel) panel.classList.add("active");
  if (tabKey === "adminnews") loadAdminNews();
  if (tabKey === "newarrival") loadNewArrivalAdmin();
  if (tabKey === "analytics") loadOpsStats();
  if (tabKey === "calendar") loadCalendar();
  if (tabKey === "libschedule") loadLibSchedule();
  if (tabKey === "issues") loadIssues();
  if (tabKey === "brequest") loadReqManage();
  if (tabKey === "staffchat") initStaffChat();
  if (tabKey === "settings") loadAdminQr();
  if (tabKey === "adminusers") loadAdminUsers();
  if (tabKey === "collections") loadAdminCollections();
  if (tabKey === "bookdesc") {
    document.getElementById("descIsbn").value = "";
    document.getElementById("descText").value = "";
    document.getElementById("descCount").textContent = "（0/600文字）";
    document.getElementById("descBookInfo").style.display = "none";
    document.getElementById("descSearchResults").style.display = "none";
    document.getElementById("descTitleSearch").value = "";
    const b2 = document.getElementById("descAwardBadges"); if (b2) b2.innerHTML = "";
    loadNoBooksReview();
  }
  // スクロールを先頭に戻す
  const boardBody = document.querySelector(".board-body");
  if (boardBody) boardBody.scrollTop = 0;
}

function _initAnalyticsSubTabs() {
  document.querySelectorAll(".analytics-sub-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".analytics-sub-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".analytics-sub-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const panel = document.getElementById("asub-" + btn.dataset.asub);
      if (panel) panel.classList.add("active");
      if (btn.dataset.asub === "stats") loadStats();
      if (btn.dataset.asub === "opsstats") loadOpsStats();
    };
  });
}

// ===== 運営統計 =====
const _GENRE_LABEL = {
  "文芸小説": "文芸小説", "その他（要分類）": "その他", "児童学習漫画": "学習漫画",
  "絵本・児童書": "絵本・児童", "時代小説・歴史小説": "時代・歴史", "児童文学": "児童文学",
  "ミステリ・推理": "ミステリ", "実用・ハウツー": "実用・HowTo", "児童学習書": "学習書",
  "ファンタジー・SF": "ファンタジー/SF", "翻訳小説": "翻訳小説", "エッセイ・評論": "エッセイ",
  "社会・ノンフィクション": "ノンフィクション", "恋愛・青春小説": "恋愛・青春",
  "科学・学術": "科学・学術", "英語絵本": "英語絵本", "児童文学・YA": "児童文学・YA",
};

async function loadOpsStats() {
  const el = document.getElementById("opsStatsContent");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const headers = { "X-Password": boardPassword };
  const [res, wishRes] = await Promise.all([
    fetch("/api/admin/ops-stats", { headers }).catch(() => null),
    fetch("/api/admin/wishlist-summary", { headers }).catch(() => null),
  ]);
  if (!res || !res.ok) { el.innerHTML = '<div class="loading">取得失敗（管理者ログインが必要です）</div>'; return; }
  const d = await res.json();
  const wishList = (wishRes && wishRes.ok) ? await wishRes.json() : [];
  const pct = r => d[r + "_total"] ? Math.round(d[r + "_done"] / d[r + "_total"] * 100) : 0;
  const bar = (p, color) => `<div style="background:#eee;border-radius:4px;height:8px;margin:4px 0 8px">
    <div style="background:${color};height:8px;border-radius:4px;width:${p}%"></div></div>`;

  const wishHtml = wishList.length
    ? wishList.map((b, i) => `
      <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #f0ede8;font-size:0.85rem">
        <span style="font-weight:700;color:#5b8dd9;min-width:28px;text-align:center;font-size:1rem">${b.wish_count}</span>
        <div>
          <div style="font-weight:600">${esc(b.title)}</div>
          ${b.author ? `<div style="color:#888;font-size:0.78rem">${esc(b.author)}</div>` : ""}
        </div>
      </div>`).join("")
    : '<div style="color:#aaa;font-size:0.85rem;padding:8px 0">まだ登録されていません</div>';

  el.innerHTML = `
    <div class="stats-summary" style="flex-wrap:wrap;gap:12px;margin-bottom:20px">
      <div class="stat-card"><div class="stat-num">${d.members}</div><div class="stat-label">👥 会員数</div></div>
      <div class="stat-card"><div class="stat-num">${d.loaned}</div><div class="stat-label">📤 現在貸出中</div></div>
      <div class="stat-card"><div class="stat-num">${d.total_cached}</div><div class="stat-label">🔍 貸出状況確認済</div></div>
      <div class="stat-card"><div class="stat-num">${d.total_votes || 0}</div><div class="stat-label">⭐ 評価投票数</div></div>
      <div class="stat-card"><div class="stat-num">${d.rated_books}</div><div class="stat-label">📚 評価された本</div></div>
    </div>

    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
      <div style="flex:1;min-width:200px">
        <h4 style="color:#3d6b4f;margin-bottom:10px">📬 リクエスト対応状況</h4>
        <div>本のリクエスト：${d.req_done}/${d.req_total}件 （${pct("req")}%）</div>
        ${bar(pct("req"), "#3d6b4f")}
        <div>ご意見・ご要望：${d.fb_done}/${d.fb_total}件 （${pct("fb")}%）</div>
        ${bar(pct("fb"), "#5b8dd9")}
      </div>
      <div style="flex:1;min-width:200px">
        <h4 style="color:#3d6b4f;margin-bottom:10px">⭐ 高評価 TOP5</h4>
        ${d.top_rated.length ? d.top_rated.map((b,i) =>
          `<div style="font-size:0.85rem;margin-bottom:5px">${i+1}. ${esc(b.title)} ${"★".repeat(Math.round(b.score))} ${b.score.toFixed(1)}（${b.votes}件）</div>`
        ).join("") : '<div style="color:#aaa;font-size:0.85rem">評価データなし</div>'}
      </div>
    </div>

    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
      <div style="flex:1;min-width:200px">
        <h4 style="color:#3d6b4f;margin-bottom:6px">📚 読みたいリスト 購入候補（上位30冊）</h4>
        <p style="font-size:0.75rem;color:#888;margin-bottom:8px">左の数字＝登録人数。複数人が希望している本は購入優先度が高いです。</p>
        ${wishHtml}
      </div>
      <div style="flex:1;min-width:200px">
        <h4 style="color:#3d6b4f;margin-bottom:10px">📂 ジャンル別蔵書数（上位10）</h4>
        <div style="display:flex;flex-direction:column;gap:5px">
          ${d.genres.map(g => {
            const maxCnt = d.genres[0]?.cnt || 1;
            const p = Math.round(g.cnt / maxCnt * 100);
            const label = _GENRE_LABEL[g.genre] || g.genre;
            return `<div style="display:flex;align-items:center;gap:8px;font-size:0.83rem">
              <span style="width:96px;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(label)}</span>
              <div style="flex:1;background:#eee;border-radius:3px;height:14px">
                <div style="background:#7ab898;height:14px;border-radius:3px;width:${p}%"></div></div>
              <span style="width:50px;text-align:right;color:#444">${g.cnt}冊</span>
            </div>`;
          }).join("")}
        </div>
      </div>
    </div>
    <div style="margin-top:20px;padding:14px;background:#f5f9f6;border:1px solid #d0e8d8;border-radius:10px">
      <h4 style="color:#3d6b4f;margin:0 0 6px">🔄 在庫状況 一括チェック</h4>
      <p style="font-size:0.78rem;color:#888;margin:0 0 10px">24時間以上未チェックの書籍をまとめて確認します（最大30冊）。完了まで数分かかる場合があります。</p>
      <button id="availRefreshBtn" onclick="runAvailabilityRefresh()"
        style="padding:8px 18px;background:#3d6b4f;color:#fff;border:none;border-radius:7px;cursor:pointer;font-size:0.85rem">
        在庫チェック開始
      </button>
      <span id="availRefreshStatus" style="margin-left:10px;font-size:0.82rem;color:#666"></span>
    </div>`;
}

async function runAvailabilityRefresh() {
  const btn = document.getElementById("availRefreshBtn");
  const statusEl = document.getElementById("availRefreshStatus");
  if (!btn || !statusEl) return;
  btn.disabled = true;
  statusEl.textContent = "対象ISBNを取得中…";
  try {
    const res = await fetch("/api/admin/availability-stale?limit=30", { headers: { "X-Password": boardPassword } });
    if (!res.ok) { statusEl.textContent = "❌ 取得失敗"; btn.disabled = false; return; }
    const items = await res.json();
    if (!items.length) { statusEl.textContent = "✅ 全て最新です"; btn.disabled = false; return; }
    let done = 0;
    for (const item of items) {
      statusEl.textContent = `チェック中… ${done}/${items.length}`;
      await fetch(`/api/availability/${encodeURIComponent(item.isbn)}`).catch(() => {});
      done++;
    }
    statusEl.textContent = `✅ ${done}件 更新完了`;
  } catch(e) {
    statusEl.textContent = "❌ エラー: " + e.message;
  }
  btn.disabled = false;
}

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
loadPopularBooks();
loadCollections();
loadTopNew();
loadReqList();
renderRecentBooks();
applyTopSectionsState();
applyFilterRowsState();
// loadGenreCounts(); // ジャンルフィルター非表示中

// 起動時: お知らせバッジ（未読カウント）を初期化
(async () => {
  try {
    const res = await fetch("/api/announcements");
    if (!res.ok) return;
    const items = await res.json();
    updateNewsBadge(items);
  } catch {}
})();

// #44 スリープ対策: 4分ごとにpingしてサービスを起こしておく
setInterval(() => fetch("/ping").catch(() => {}), 4 * 60 * 1000);

// スリープ復帰バナー: /ping が5秒以内に応答しない場合に表示
(function() {
  const banner = document.getElementById("wakeupBanner");
  const secEl  = document.getElementById("wakeupSec");
  if (!banner) return;
  let shown = false, counterTimer = null, counter = 0;
  const showTimer = setTimeout(() => {
    shown = true;
    banner.style.display = "block";
    counterTimer = setInterval(() => { counter++; if (secEl) secEl.textContent = counter; }, 1000);
  }, 5000);
  function hideWakeupBanner() {
    clearTimeout(showTimer);
    if (counterTimer) clearInterval(counterTimer);
    if (shown) { banner.style.opacity = "0"; banner.style.transition = "opacity 0.5s"; setTimeout(() => banner.style.display = "none", 500); }
  }
  function tryPing() {
    fetch("/ping").then(hideWakeupBanner).catch(() => setTimeout(tryPing, 4000));
  }
  tryPing();
})();

// ===== Book Requests =====
let residentPassword = sessionStorage.getItem("resident_pass") || "";
let reqAdminPass = "";

// residentPasswordは新認証システムではresidentSession.passwordで管理

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

function _updateReqAuthUI() {
  const u = residentSession || getCloudUser();
  const notice = document.getElementById("reqAuthNotice");
  const fbNotice = document.getElementById("fbAuthNotice");
  const roomEl = document.getElementById("reqRoom");
  const passEl = document.getElementById("reqPass");
  const fbRoomEl = document.getElementById("fbRoom");
  const fbPassEl = document.getElementById("fbPass");
  if (u) {
    const label = `<span style="color:#3d6b4f;font-weight:600">✅ ログイン中（${u.room}）</span><span style="color:#888;font-size:0.8rem"> — この部屋番号で送信します</span>`;
    if (notice) notice.innerHTML = label;
    if (fbNotice) fbNotice.innerHTML = label;
    if (roomEl) roomEl.value = u.room;
    if (passEl) passEl.value = u.password || u.pin || "";
    if (fbRoomEl) fbRoomEl.value = u.room;
    if (fbPassEl) fbPassEl.value = u.password || u.pin || "";
  } else {
    const msg = `<span style="color:#c00">🔒 リクエストにはログインが必要です。</span><br><a href="#" onclick="document.getElementById('loginScreen').style.display='flex';return false;" style="font-size:0.85rem;color:#5b8dd9">ログイン / 新規登録はこちら →</a>`;
    if (notice) notice.innerHTML = msg;
    if (fbNotice) fbNotice.innerHTML = msg;
    if (roomEl) roomEl.value = "";
    if (passEl) passEl.value = "";
    if (fbRoomEl) fbRoomEl.value = "";
    if (fbPassEl) fbPassEl.value = "";
  }
}
_updateReqAuthUI();

document.getElementById("reqSubmitBtn").addEventListener("click", async () => {
  const title = document.getElementById("reqTitle").value.trim();
  const author = document.getElementById("reqAuthor").value.trim();
  const reason = document.getElementById("reqReason").value.trim();
  const room = document.getElementById("reqRoom").value.trim();
  const password = document.getElementById("reqPass").value.trim();
  const msg = document.getElementById("reqMsg");
  if (!title) { msg.textContent = "⚠️ 書名を入力してください"; msg.style.color = "#e05"; return; }
  if (!room || !password) {
    msg.textContent = "⚠️ リクエストにはログインが必要です";
    msg.style.color = "#c00"; return;
  }
  const btn = document.getElementById("reqSubmitBtn");
  btn.disabled = true; btn.textContent = "送信中…";
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title, author, reason, room, password})
  });
  btn.disabled = false; btn.textContent = "📨 リクエストを送る";
  if (res.ok) {
    msg.textContent = "✅ リクエストを送信しました！ありがとうございます。";
    msg.style.color = "#3d6b4f";
    document.getElementById("reqTitle").value = "";
    document.getElementById("reqAuthor").value = "";
    document.getElementById("reqReason").value = "";
    showReqToast("✅ リクエストを送信しました！");
  } else if (res.status === 429) {
    msg.textContent = "⚠️ 送信が多すぎます。しばらく時間をおいてから再試行してください。";
    msg.style.color = "#e07800";
  } else if (res.status === 401) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = "❌ " + (d.error || "認証エラーです。ログインし直してください");
    msg.style.color = "#c00";
  } else {
    msg.textContent = "❌ 送信できませんでした。もう一度お試しください。";
    msg.style.color = "#e05";
  }
});

// ===== 図書館へのご要望フォーム =====
document.getElementById("fbSubmitBtn").addEventListener("click", async () => {
  const title = document.getElementById("fbTitle").value.trim();
  const fbBody = document.getElementById("fbBody").value.trim();
  const room = document.getElementById("fbRoom").value.trim();
  const password = document.getElementById("fbPass").value.trim();
  const msg = document.getElementById("fbMsg");
  if (!title) { msg.textContent = "⚠️ 件名を入力してください"; msg.style.color = "#e05"; return; }
  if (!fbBody) { msg.textContent = "⚠️ 内容を入力してください"; msg.style.color = "#e05"; return; }
  if (!room || !password) {
    msg.textContent = "⚠️ ご要望にはログインが必要です";
    msg.style.color = "#c00"; return;
  }
  const btn = document.getElementById("fbSubmitBtn");
  btn.disabled = true; btn.textContent = "送信中…";
  const res = await fetch("/api/requests", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({title, author: "", reason: fbBody, room, password, type: "feedback"})
  });
  btn.disabled = false; btn.textContent = "📩 送信する";
  if (res.ok) {
    msg.textContent = "✅ 送信しました！ありがとうございます。";
    msg.style.color = "#3d6b4f";
    document.getElementById("fbTitle").value = "";
    document.getElementById("fbBody").value = "";
    showReqToast("✅ ご要望を送信しました！");
  } else if (res.status === 401) {
    const d = await res.json().catch(() => ({}));
    msg.textContent = "❌ " + (d.error || "認証エラーです。ログインし直してください");
    msg.style.color = "#c00";
  } else {
    msg.textContent = "❌ 送信できませんでした。もう一度お試しください。";
    msg.style.color = "#e05";
  }
});

function getVotedIds() {
  try { return JSON.parse(localStorage.getItem("voted_requests") || "[]"); } catch { return []; }
}
function saveVotedIds(ids) { localStorage.setItem("voted_requests", JSON.stringify(ids)); }

function reqResidentCardHtml(r, votedIds, myRoom) {
  const isFb = r.type === "feedback";
  const stLabel = {pending: isFb ? "📬 受付中" : "⏳ 検討中", approved:"✅ 購入決定", rejected:"❌ 見送り", done:"📦 入荷済",
    fb_received:"📬 受付中", fb_checking:"🔍 確認中", fb_done:"✅ 対応済", fb_rejected:"❌ 見送り",
    fb_pending:"⏳ 検討中", fb_noted:"📝 参考意見として受理", fb_none:"➖ 対応なし"};
  const stColor = {pending: isFb ? "#888" : "#888", approved:"#3d8a4f", rejected:"#c00", done:"#555",
    fb_received:"#888", fb_checking:"#5b8dd9", fb_done:"#3d8a4f", fb_rejected:"#c00",
    fb_pending:"#888", fb_noted:"#7a5c9a", fb_none:"#aaa"};
  const voted = votedIds.includes(r.id);
  const votes = r.votes || 0;
  const isOwn = myRoom && r.room === myRoom;
  const borderColor = isFb ? "#5b8dd9" : "#3d6b4f";
  const bgColor = isFb ? "#f0f5ff" : "#f2f8f4";
  const ownBadge = isOwn ? `<span style="font-size:0.72rem;color:#fff;background:#7a9a5c;border-radius:10px;padding:1px 7px;margin-left:6px">あなたの投稿</span>` : "";
  const voteBtn = isFb ? "" : `
    <button class="req-vote-btn${voted?" req-vote-done":""}" data-id="${r.id}" ${(r.status==="done"||r.status==="rejected")?"disabled":""}>
      👍 <span class="req-vote-count">${votes}</span>${voted?" 済":" 読みたい"}
    </button>`;
  return `
  <div class="req-card" data-id="${r.id}" style="border-left:5px solid ${borderColor};background:${bgColor}${isOwn?";box-shadow:0 0 0 1.5px "+borderColor:""}">
    <div class="req-card-header">
      <div class="req-card-left">
        <span class="req-book-title">${esc(r.title)}</span>
        ${r.author ? `<span class="req-author-badge">著：${esc(r.author)}</span>` : ""}
        ${ownBadge}
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
    const myRoom = (residentSession || getCloudUser() || {}).room || "";

    const books = items.filter(r => r.type !== "feedback");
    const fbs = items.filter(r => r.type === "feedback");

    elBooks.innerHTML = books.length ? books.map(r => reqResidentCardHtml(r, votedIds, myRoom)).join("") : '<div class="loading">まだ本のリクエストはありません</div>';
    if (elFb) elFb.innerHTML = fbs.length ? fbs.map(r => reqResidentCardHtml(r, votedIds, myRoom)).join("") : '<div class="loading">まだご要望・ご意見はありません</div>';

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
  const REPLY_PROMPT_STATUSES = new Set(["fb_done", "fb_rejected", "fb_noted", "fb_none", "approved", "rejected", "done"]);
  container.querySelectorAll(".req-status-sel").forEach(sel => {
    sel.addEventListener("change", async () => {
      const card = sel.closest(".req-admin-card");
      const replyTA = card && card.querySelector(".req-reply-input");
      if (REPLY_PROMPT_STATUSES.has(sel.value) && replyTA && !replyTA.value.trim()) {
        replyTA.style.borderColor = "#e08a00";
        replyTA.placeholder = "⚠️ 返答を入力してから保存してください（居住者に表示されます）";
        replyTA.focus();
        sel.value = sel.dataset.prev || sel.value;
        return;
      }
      sel.dataset.prev = sel.value;
      await fetch(`/api/requests/${sel.dataset.id}`, {
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({password: reqAdminPass, status: sel.value})
      });
      loadReqManage();
    });
    sel.addEventListener("focus", () => { sel.dataset.prev = sel.value; });
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
  container.querySelectorAll(".req-reply-input").forEach(ta => {
    ta.addEventListener("input", () => { ta.style.borderColor = "#5b8dd9"; });
  });
  container.querySelectorAll(".req-reply-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const ta = container.querySelector(`.req-reply-input[data-id="${id}"]`);
      const reply = ta.value.trim();
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
  const u = residentSession || getCloudUser();
  if (!u) return;
  const favs = getFavIsbns();
  const rlog = {};
  getLogEntries().forEach(e => {
    const meta = getReadMeta(e.isbn);
    rlog[e.isbn] = meta.due_date ? {status: e.status, due_date: meta.due_date} : e.status;
  });
  const card_url = localStorage.getItem("libraryCardUrl") || "";
  const card_img = localStorage.getItem("libraryCardImage") || "";
  const pw = u.password || u.pin || "";
  try {
    await fetch("/api/user/sync", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({room: u.room, password: pw, favorites: favs, reading_log: rlog,
        library_card_url: card_url, library_card_image: card_img})
    });
    const fc = document.getElementById("syncFavCount");
    const lc = document.getElementById("syncLogCount");
    if (fc) fc.textContent = favs.length;
    if (lc) lc.textContent = Object.keys(rlog).length;
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
  _migrateReadKeysToRoom(room);
  updateSyncUI();

  // クラウドデータをローカルにマージ
  if (!data.is_new) {
    (data.favorites || []).forEach(isbn => localStorage.setItem("fav_" + isbn, "1"));
    Object.entries(data.reading_log || {}).forEach(([isbn, status]) => {
      if (status) localStorage.setItem(`read_${room}_${isbn}`, status);
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
  const res = await fetch(`/api/admin/db-size`, { headers: { "X-Password": boardPassword } });
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
  const dbBtn = document.getElementById("dbSizeBtn");
  if (dbBtn) dbBtn.addEventListener("click", loadDbSize);
}

// ===== Admin QR =====
// ===== 管理者アカウント管理 =====
async function loadAdminUsers() {
  const el = document.getElementById("adminUsersContent");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  const res = await fetch(`/api/admin/users`, { headers: { "X-Password": boardPassword } });
  if (!res.ok) { el.innerHTML = '<div class="loading">読み込みに失敗しました</div>'; return; }
  const users = await res.json();
  const roleLabel = r => r === "master" ? '<span class="au-role au-master">マスター</span>' : '<span class="au-role au-admin">管理者</span>';
  const myCode = adminSession ? adminSession.code : "";
  el.innerHTML = `
    <div class="au-list">
      ${users.map(u => `
        <div class="au-row" data-code="${esc(u.code)}">
          <div class="au-info">
            <span class="au-code">${esc(u.code)}</span>
            <span class="au-name">${esc(u.name)}</span>
            ${roleLabel(u.role)}
            <span class="au-date">${u.created_at}</span>
          </div>
          <div class="au-actions">
            <button class="au-pw-btn" data-code="${esc(u.code)}" data-name="${esc(u.name)}">🔑 PW変更</button>
            ${u.code !== myCode ? `<button class="au-del-btn" data-code="${esc(u.code)}" data-name="${esc(u.name)}">🗑 削除</button>` : '<span class="au-self-label">（自分）</span>'}
          </div>
        </div>`).join("")}
    </div>
    <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
    <h4 style="margin:0 0 12px;font-size:0.95rem;color:#555">＋ 新しい管理者を追加</h4>
    <div class="au-form">
      <input type="text" id="auNewCode" placeholder="コード（例: A001）" class="au-input" maxlength="10">
      <input type="text" id="auNewName" placeholder="氏名" class="au-input" maxlength="20">
      <input type="password" id="auNewPass" placeholder="初期パスワード（8文字以上）" class="au-input">
      <select id="auNewRole" class="au-input">
        <option value="admin">管理者</option>
        <option value="master">マスター</option>
      </select>
      <button id="auAddBtn" class="btn-primary">追加</button>
      <p id="auMsg" style="margin-top:8px;font-size:0.85rem;color:#e05"></p>
    </div>
    <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
    <h4 style="margin:0 0 12px;font-size:0.95rem;color:#555">🔒 自分のパスワード変更</h4>
    <div class="au-form">
      <input type="password" id="auSelfCurPass" placeholder="現在のパスワード" class="au-input">
      <input type="password" id="auSelfNewPass" placeholder="新しいパスワード（8文字以上）" class="au-input">
      <button id="auSelfPwBtn" class="btn-primary">変更</button>
      <p id="auSelfMsg" style="margin-top:8px;font-size:0.85rem"></p>
    </div>`;

  // 削除ボタン
  el.querySelectorAll(".au-del-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const code = btn.dataset.code;
      const name = btn.dataset.name;
      if (!confirm(`${name}（${code}）を削除しますか？`)) return;
      const curPass = prompt("マスターパスワードを入力してください：");
      if (!curPass) return;
      const r = await fetch(`/api/admin/users/${code}`, {
        method: "DELETE", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({req_code: myCode, req_password: curPass})
      });
      const d = await r.json();
      if (r.ok) loadAdminUsers();
      else alert("❌ " + (d.error || "削除に失敗しました"));
    });
  });

  // PW変更ボタン（マスターによる他者のリセット）
  el.querySelectorAll(".au-pw-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const targetCode = btn.dataset.code;
      const targetName = btn.dataset.name;
      if (targetCode === myCode) {
        document.getElementById("auSelfCurPass")?.focus();
        return;
      }
      const newPw = prompt(`${targetName}（${targetCode}）の新しいパスワードを入力：`);
      if (!newPw) return;
      const curPass = prompt("マスターパスワードを入力してください：");
      if (!curPass) return;
      const r = await fetch(`/api/admin/users/${targetCode}/password`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({req_code: myCode, req_password: curPass, new_password: newPw})
      });
      const d = await r.json();
      alert(r.ok ? "✅ パスワードを変更しました" : "❌ " + (d.error || "失敗しました"));
    });
  });

  // 新規追加
  document.getElementById("auAddBtn")?.addEventListener("click", async () => {
    const code = (document.getElementById("auNewCode").value || "").trim().toUpperCase();
    const name = (document.getElementById("auNewName").value || "").trim();
    const pass = document.getElementById("auNewPass").value;
    const role = document.getElementById("auNewRole").value;
    const msg = document.getElementById("auMsg");
    msg.style.color = "#e05";
    if (!code || !name || !pass) { msg.textContent = "コード・氏名・パスワードを入力してください"; return; }
    const curPass = prompt("マスターパスワードを入力してください：");
    if (!curPass) return;
    const r = await fetch("/api/admin/users", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({req_code: myCode, req_password: curPass, code, name, password: pass, role})
    });
    const d = await r.json();
    if (r.ok) { msg.style.color = "#2a7"; msg.textContent = "✅ 追加しました"; loadAdminUsers(); }
    else { msg.textContent = "❌ " + (d.error || "失敗しました"); }
  });

  // 自分のPW変更
  document.getElementById("auSelfPwBtn")?.addEventListener("click", async () => {
    const curPass = document.getElementById("auSelfCurPass").value;
    const newPw = document.getElementById("auSelfNewPass").value;
    const msg = document.getElementById("auSelfMsg");
    if (!curPass || !newPw) { msg.style.color = "#e05"; msg.textContent = "現在・新しいパスワードを両方入力してください"; return; }
    const r = await fetch(`/api/admin/users/${myCode}/password`, {
      method: "PATCH", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({req_code: myCode, req_password: curPass, new_password: newPw})
    });
    const d = await r.json();
    if (r.ok) {
      msg.style.color = "#2a7"; msg.textContent = "✅ パスワードを変更しました";
      boardPassword = newPw;
      sessionStorage.setItem("board_pass", newPw);
      document.getElementById("auSelfCurPass").value = "";
      document.getElementById("auSelfNewPass").value = "";
    } else {
      msg.style.color = "#e05"; msg.textContent = "❌ " + (d.error || "失敗しました");
    }
  });
}

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
      iframe.onload = () => {
        clearTimeout(iframeTimer);
        // 同一オリジンで読めた場合に404チェック
        try {
          const doc = iframe.contentDocument || iframe.contentWindow?.document;
          if (doc && (doc.title.includes("404") || doc.body?.innerText.includes("NOT FOUND") || doc.body?.innerText.includes("404"))) {
            iframe.style.display = "none";
            errEl.innerHTML = `⚠️ 会員証URLが無効（404）です。URLが変更されました。<br>
              <button onclick="document.getElementById('cardResetBtn').click()" style="margin-top:8px;padding:6px 14px;background:#e65100;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.82rem">
                🔄 URLを再登録する
              </button>`;
            errEl.style.display = "";
          }
        } catch(e) {
          // cross-origin の場合は確認不可 → そのまま
        }
      };

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

// --- スレッド機能 ---
let currentThreadId = null;
let currentChatMode = "general"; // "general" | "threads" | "thread_detail"
let threadPollTimer = null;

function switchChatMode(mode) {
  currentChatMode = mode;
  document.getElementById("chatViewGeneral").style.display = mode === "general" ? "flex" : "none";
  document.getElementById("chatViewThreadList").style.display = mode === "threads" ? "flex" : "none";
  document.getElementById("chatViewThreadDetail").style.display = mode === "thread_detail" ? "flex" : "none";
  document.getElementById("chatModeGeneral").classList.toggle("chat-mode-active", mode === "general");
  document.getElementById("chatModeThread").classList.toggle("chat-mode-active", mode === "threads" || mode === "thread_detail");
  if (mode === "threads") loadThreadList();
}

async function loadThreadList() {
  const box = document.getElementById("chatThreadList");
  if (!box) return;
  try {
    const res = await fetch(`/api/chat_threads`, { headers: { "X-Password": boardPassword } });
    if (!res.ok) return;
    const threads = await res.json();
    if (!threads.length) {
      box.innerHTML = '<div style="text-align:center;color:#bbb;padding:30px 0;font-size:0.9rem">スレッドはまだありません<br>「＋ 新スレッド」から作成できます</div>';
      return;
    }
    box.innerHTML = threads.map(t => `
      <div class="thread-card" data-thread-id="${t.id}" data-thread-title="${esc(t.title)}">
        <div class="thread-card-title">${esc(t.title)}</div>
        <div class="thread-card-meta">
          <span>📝 ${t.msg_count}件</span>
          <span>🕐 ${t.last_at || t.created_at}</span>
          <span>作成: ${esc(t.created_by)}</span>
        </div>
      </div>
    `).join("");
    box.querySelectorAll(".thread-card").forEach(card => {
      card.addEventListener("click", () => openThread(Number(card.dataset.threadId), card.dataset.threadTitle));
    });
  } catch(e) { console.error("thread list error", e); }
}

async function openThread(threadId, title) {
  currentThreadId = threadId;
  document.getElementById("chatThreadTitle").textContent = title;
  currentChatMode = "thread_detail";
  document.getElementById("chatViewGeneral").style.display = "none";
  document.getElementById("chatViewThreadList").style.display = "none";
  document.getElementById("chatViewThreadDetail").style.display = "flex";
  document.getElementById("chatModeThread").classList.add("chat-mode-active");
  await loadThreadMessages(true);
  if (threadPollTimer) clearInterval(threadPollTimer);
  threadPollTimer = setInterval(() => loadThreadMessages(), 5000);
}

async function loadThreadMessages(scrollToBottom = false) {
  const box = document.getElementById("chatThreadMessages");
  if (!box || !currentThreadId) return;
  try {
    const res = await fetch(`/api/staff_chat?thread_id=${currentThreadId}`, { headers: { "X-Password": boardPassword } });
    if (!res.ok) return;
    const msgs = await res.json();
    msgs.reverse();
    if (!msgs.length) {
      box.innerHTML = '<div style="text-align:center;color:#bbb;padding:30px 0;font-size:0.9rem">まだメッセージはありません</div>';
      return;
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
        loadThreadMessages();
      });
    });
    if (scrollToBottom || atBottom) box.scrollTop = box.scrollHeight;
  } catch(e) { console.error("thread msg error", e); }
}

function initThreadUI() {
  // 戻るボタン
  const backBtn = document.getElementById("chatBackToThreads");
  if (backBtn) backBtn.onclick = () => {
    if (threadPollTimer) { clearInterval(threadPollTimer); threadPollTimer = null; }
    currentThreadId = null;
    switchChatMode("threads");
  };

  // スレッド削除
  const delBtn = document.getElementById("chatThreadDeleteBtn");
  if (delBtn) delBtn.onclick = async () => {
    if (!currentThreadId) return;
    if (!confirm("このスレッドとメッセージを全て削除しますか？")) return;
    await fetch(`/api/chat_threads/${currentThreadId}`, {
      method: "DELETE", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({password: boardPassword})
    });
    if (threadPollTimer) { clearInterval(threadPollTimer); threadPollTimer = null; }
    currentThreadId = null;
    switchChatMode("threads");
  };

  // 新スレッドボタン
  const newBtn = document.getElementById("chatNewThreadBtn");
  const newForm = document.getElementById("chatNewThreadForm");
  if (newBtn && newForm) {
    newBtn.onclick = () => { newForm.style.display = newForm.style.display === "none" ? "block" : "none"; };
  }
  const cancelBtn = document.getElementById("chatNewThreadCancel");
  if (cancelBtn) cancelBtn.onclick = () => { newForm.style.display = "none"; };

  const submitBtn = document.getElementById("chatNewThreadSubmit");
  if (submitBtn) submitBtn.onclick = async () => {
    const title = (document.getElementById("chatNewThreadTitle").value || "").trim();
    const msg = (document.getElementById("chatNewThreadMsg").value || "").trim();
    if (!title) { alert("タイトルを入力してください"); return; }
    const sender = boardSenderName || "匿名";
    const res = await fetch("/api/chat_threads", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({password: boardPassword, title, created_by: sender, first_message: msg})
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      document.getElementById("chatNewThreadTitle").value = "";
      document.getElementById("chatNewThreadMsg").value = "";
      newForm.style.display = "none";
      openThread(data.thread_id, title);
    } else {
      alert(data.error || "作成に失敗しました");
    }
  };

  // スレッド内送信
  const threadInput = document.getElementById("chatThreadInput");
  const threadSendBtn = document.getElementById("chatThreadSendBtn");
  const threadImgInput = document.getElementById("chatThreadImgInput");
  let threadPendingImage = "";

  if (threadImgInput) {
    threadImgInput.onchange = async () => {
      const file = threadImgInput.files[0];
      if (!file) return;
      threadPendingImage = await compressImage(file);
      threadImgInput.value = "";
    };
  }

  const sendThread = async () => {
    if (!currentThreadId) return;
    const msg = (threadInput ? threadInput.value.trim() : "");
    if (!msg && !threadPendingImage) return;
    const sender = boardSenderName || "匿名";
    if (threadInput) threadInput.value = "";
    if (threadSendBtn) threadSendBtn.disabled = true;
    const image_data = threadPendingImage;
    threadPendingImage = "";
    await fetch("/api/staff_chat", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({password: boardPassword, sender, message: msg, image_data, thread_id: currentThreadId})
    });
    if (threadSendBtn) threadSendBtn.disabled = false;
    loadThreadMessages(true);
    if (threadInput) threadInput.focus();
  };

  if (threadSendBtn) threadSendBtn.onclick = sendThread;
  if (threadInput) threadInput.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendThread(); } };
}

async function loadChatMessages(scrollToBottom = false) {
  const box = document.getElementById("chatMessages");
  if (!box) return;
  try {
    const res = await fetch(`/api/staff_chat`, { headers: { "X-Password": boardPassword } });
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

  initThreadUI();
  switchChatMode("threads");
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

// ===== 特集コーナー =====
async function loadPopularBooks() {
  const sec = document.getElementById("popularSection");
  const row = document.getElementById("popularRow");
  if (!sec || !row) return;
  try {
    const res = await fetch("/api/books/popular");
    if (!res.ok) return;
    const books = await res.json();
    if (!books.length) return;
    sec.style.display = "block";
    applySectionState("popular");
    row.innerHTML = books.map(b => {
      const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
      const stars = b.score ? "★".repeat(Math.round(b.score)) + "☆".repeat(5 - Math.round(b.score)) : "";
      return `<div class="mini-card" data-isbn="${b.isbn}">
        <div class="mini-card-cover"><img src="${b.cover || ndlFallback}" alt="${esc(b.title)}" loading="lazy"
          onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.replaceWith(Object.assign(document.createElement('div'),{className:'mini-card-placeholder',textContent:'📖'}));}"></div>
        <div class="mini-card-title">${esc(b.title)}</div>
        <div style="color:#f0a500;font-size:0.72rem;margin-top:2px">${stars} ${b.score.toFixed(1)}</div>
      </div>`;
    }).join("");
    row.querySelectorAll(".mini-card").forEach(el => {
      el.addEventListener("click", () => openModal(el.dataset.isbn));
    });
  } catch {}
}

async function loadCollections() {
  const sec = document.getElementById("collectionsSection");
  const list = document.getElementById("collectionsList");
  if (!sec || !list) return;
  try {
    const res = await fetch("/api/collections");
    if (!res.ok) return;
    const cols = await res.json();
    if (!cols.length) { sec.style.display = "none"; return; }
    sec.style.display = "block";
    list.innerHTML = cols.map(c => `
      <div class="collection-block">
        <div class="collection-header">${c.emoji} <strong>${esc(c.title)}</strong>${c.description ? ` <span class="collection-desc">${esc(c.description)}</span>` : ""}</div>
        <div class="collection-count">${c.count}冊</div>
        <div class="related-carousel" id="col-books-${c.id}"><div class="loading" style="font-size:0.8rem">読み込み中…</div></div>
      </div>
    `).join("");
    // 各特集の本を取得
    for (const c of cols) {
      if (!c.isbns.length) continue;
      try {
        const br = await fetch(`/api/books/batch?isbns=${c.isbns.join(",")}`);
        const books = await br.json();
        const container = document.getElementById(`col-books-${c.id}`);
        if (!container) continue;
        const items = books.filter(Boolean).map(b => {
          const ndlFallback = `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
          return `<div class="related-card" onclick="openModal('${b.isbn}')" role="button" tabindex="0">
            <div class="related-thumb"><img src="${b.cover || ndlFallback}" alt="${esc(b.title)}" loading="lazy" onerror="if(this.src!=='${ndlFallback}'){this.src='${ndlFallback}';}else{this.style.display='none';}"></div>
            <div class="related-title">${esc(b.title)}</div>
            <div class="related-author">${esc(b.author || "")}</div>
          </div>`;
        }).join("");
        container.innerHTML = items || "<span style='color:#aaa;font-size:0.8rem'>本が見つかりません</span>";
      } catch {}
    }
  } catch {}
}

async function loadAdminCollections() {
  const list = document.getElementById("adminCollectionList");
  if (!list) return;
  list.innerHTML = '<div class="loading">読み込み中…</div>';
  try {
  const res = await fetch("/api/collections?all=1");
  if (!res.ok) { list.innerHTML = `<div style="color:#c44;padding:16px">取得エラー (${res.status})</div>`; return; }
  const cols = await res.json();
  if (!Array.isArray(cols) || !cols.length) { list.innerHTML = '<div style="color:#aaa;padding:20px;text-align:center">まだ特集はありません<br>「＋ 新規特集」から作成できます</div>'; return; }
  list.innerHTML = cols.map(c => `
    <div class="col-admin-card" data-id="${c.id}">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:1.3rem">${c.emoji}</span>
        <div style="flex:1">
          <div style="font-weight:700">${esc(c.title)}</div>
          ${c.description ? `<div style="font-size:0.8rem;color:#888">${esc(c.description)}</div>` : ""}
          <div style="font-size:0.78rem;color:#aaa">ISBN ${c.count}冊 | 並び順: ${c.sort_order}</div>
        </div>
        <div style="display:flex;gap:6px">
          <button class="col-toggle-btn" data-id="${c.id}" data-active="${c.is_active}" style="padding:5px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;font-size:0.8rem">${c.is_active ? "表示中" : "非表示"}</button>
          <button class="col-del-btn" data-id="${c.id}" style="padding:5px 10px;border:1px solid #fcc;border-radius:6px;background:#fff;color:#c44;cursor:pointer;font-size:0.8rem">削除</button>
        </div>
      </div>
    </div>
  `).join("");
  list.querySelectorAll(".col-toggle-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const newActive = btn.dataset.active === "true" ? false : true;
      await fetch(`/api/collections/${btn.dataset.id}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword, is_active: newActive})
      });
      loadAdminCollections();
    });
  });
  list.querySelectorAll(".col-del-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("この特集を削除しますか？")) return;
      await fetch(`/api/collections/${btn.dataset.id}`, {
        method: "DELETE", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({password: boardPassword})
      });
      loadAdminCollections();
    });
  });
  // フォームトグル（onclick = 重複登録防止）
  const _toggleBtn = document.getElementById("collectionFormToggle");
  if (_toggleBtn) _toggleBtn.onclick = () => {
    const f = document.getElementById("collectionForm");
    if (f) f.style.display = f.style.display === "none" ? "block" : "none";
  };
  const _cancelBtn = document.getElementById("collectionFormCancel");
  if (_cancelBtn) _cancelBtn.onclick = () => {
    document.getElementById("collectionForm").style.display = "none";
  };
  const _submitBtn = document.getElementById("collectionSubmitBtn");
  if (_submitBtn) _submitBtn.onclick = async () => {
    const title = (document.getElementById("colTitle")?.value || "").trim();
    const desc = (document.getElementById("colDesc")?.value || "").trim();
    const emoji = (document.getElementById("colEmoji")?.value || "📚").trim();
    const isbnRaw = (document.getElementById("colIsbns")?.value || "");
    const isbns = isbnRaw.split(/[\n,]/).map(s => s.trim().replace(/-/g,"")).filter(s => /^\d{10,13}$/.test(s));
    const msg = document.getElementById("collectionMsg");
    if (!title) { if (msg) { msg.textContent = "タイトルを入力してください"; msg.style.color = "#e05"; } return; }
    const res = await fetch("/api/collections", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({password: boardPassword, title, description: desc, emoji, isbns})
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      if (msg) { msg.textContent = "✅ 作成しました"; msg.style.color = "#3d6b4f"; }
      document.getElementById("colTitle").value = "";
      document.getElementById("colDesc").value = "";
      document.getElementById("colIsbns").value = "";
      document.getElementById("collectionForm").style.display = "none";
      loadAdminCollections();
    } else {
      if (msg) { msg.textContent = "❌ " + (data.error || "作成失敗"); msg.style.color = "#e05"; }
    }
  };
  } catch(e) {
    list.innerHTML = `<div style="color:#c44;padding:16px">読み込みエラー: ${e.message}</div>`;
  }
}

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

// ── 受賞情報（管理者） ────────────────────────────────────────────────────
const AWARD_OPTIONS = [
  "本屋大賞","本屋大賞ノミネート","直木賞","芥川賞",
  "山本周五郎賞","谷崎潤一郎賞","三島由紀夫賞","野間文芸賞",
  "読売文学賞","川端康成文学賞","吉川英治文学賞","柴田錬三郎賞",
  "江戸川乱歩賞","日本推理作家協会賞","このミステリーがすごい！大賞",
  "本格ミステリ大賞","鮎川哲也賞","日本SF大賞","星雲賞",
  "日本ファンタジーノベル大賞","日本ホラー小説大賞",
  "小説すばる新人賞","オール讀物新人賞","新潮新人賞","群像新人文学賞",
  "文學界新人賞","すばる文学賞","メフィスト賞","電撃小説大賞",
];

function addAwardEntry(award = "", year = new Date().getFullYear(), type = "winner", rank = "") {
  const container = document.getElementById("awardEntries");
  const idx = container.children.length;
  const div = document.createElement("div");
  div.className = "award-entry";
  div.style.cssText = "display:flex;gap:6px;align-items:center;background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:8px;flex-wrap:wrap;";
  div.innerHTML = `
    <select class="award-entry-name" style="flex:2;min-width:140px;padding:6px;border:1px solid #ddd;border-radius:6px;font-size:0.82rem">
      ${AWARD_OPTIONS.map(a => `<option value="${a}" ${a===award?"selected":""}>${a}</option>`).join("")}
    </select>
    <input class="award-entry-year" type="number" value="${year}" min="1950" max="2099" style="width:70px;padding:6px;border:1px solid #ddd;border-radius:6px;font-size:0.82rem" placeholder="年">
    <select class="award-entry-type" style="padding:6px;border:1px solid #ddd;border-radius:6px;font-size:0.82rem">
      <option value="winner" ${type==="winner"?"selected":""}>受賞</option>
      <option value="nominee" ${type==="nominee"?"selected":""}>候補/ノミネート</option>
    </select>
    <input class="award-entry-rank" type="number" value="${rank}" min="1" max="10" style="width:54px;padding:6px;border:1px solid #ddd;border-radius:6px;font-size:0.82rem" placeholder="順位">
    <button onclick="this.parentElement.remove()" style="background:#fee;border:1px solid #fcc;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:0.82rem">✕</button>`;
  container.appendChild(div);
}

async function saveBookAwards() {
  const isbn = document.getElementById("descIsbn").value.trim();
  const msg = document.getElementById("awardMsg");
  if (!isbn) { msg.textContent = "⚠️ 上のISBNを入力してください"; return; }
  const entries = [...document.getElementById("awardEntries").children].map(div => {
    const award = div.querySelector(".award-entry-name").value;
    const year = parseInt(div.querySelector(".award-entry-year").value) || null;
    const type = div.querySelector(".award-entry-type").value;
    const rank = parseInt(div.querySelector(".award-entry-rank").value) || null;
    return { award, year, type, ...(rank ? {rank} : {}) };
  });
  const pass = sessionStorage.getItem("board_pass") || boardPassword;
  if (!pass) { msg.textContent = "⚠️ 再ログインしてください"; return; }
  msg.textContent = "保存中...";
  try {
    const res = await fetch("/api/book-award", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: pass, isbn, awards: entries})
    });
    if (res.ok) {
      msg.textContent = "✅ 受賞情報を保存しました";
      document.getElementById("awardEntries").innerHTML = "";
      setTimeout(() => { msg.textContent = ""; }, 3000);
    } else {
      const err = await res.json().catch(() => ({}));
      msg.textContent = "❌ 保存失敗: " + (err.error || res.status);
    }
  } catch(e) {
    msg.textContent = "❌ 通信エラー";
  }
}

// ISBNが入力されたとき既存の受賞情報もロード
async function lookupBookAwards(isbn) {
  const res = await fetch(`/api/book-awards/${isbn}`).catch(() => null);
  if (!res || !res.ok) return;
  const data = await res.json();
  const container = document.getElementById("awardEntries");
  container.innerHTML = "";
  (data.awards || []).forEach(a => addAwardEntry(a.award, a.year, a.type, a.rank || ""));
  // 書評入力画面の受賞バッジ表示
  const badgeEl = document.getElementById("descAwardBadges");
  if (badgeEl) {
    const html = renderAwardBadges(data.awards || []);
    badgeEl.innerHTML = html || '<span style="font-size:0.78rem;color:#aaa">受賞歴なし（または未登録）</span>';
  }
}

// ── 書評入力（管理者） ─────────────────────────────────────────────────────
async function searchBookForDesc() {
  const kw = (document.getElementById("descTitleSearch").value || "").trim();
  if (!kw) return;
  const grid = document.getElementById("descSearchGrid");
  const wrap = document.getElementById("descSearchResults");
  grid.innerHTML = '<span style="font-size:0.82rem;color:#888">検索中...</span>';
  wrap.style.display = "block";
  try {
    const res = await fetch(`/api/books/by-genre?keyword=${encodeURIComponent(kw)}&per=30`);
    const data = await res.json();
    const books = data.books || [];
    if (!books.length) {
      grid.innerHTML = '<span style="font-size:0.82rem;color:#888">該当する本が見つかりませんでした</span>';
      return;
    }
    grid.innerHTML = books.map(b => {
      const isbn10 = b.isbn10 || "";
      const cover = isbn10
        ? `https://images-na.ssl-images-amazon.com/images/P/${isbn10}.09.LZZZZZZZ.jpg`
        : `https://ndlsearch.ndl.go.jp/thumbnail/${b.isbn}.jpg`;
      return `<div onclick="selectDescBook('${esc(b.isbn)}','${esc(b.title)}')"
        style="cursor:pointer;text-align:center;padding:4px;border-radius:8px;border:2px solid transparent;transition:border-color .15s"
        onmouseover="this.style.borderColor='#3d6b4f'" onmouseout="this.style.borderColor='transparent'">
        <img src="${cover}" alt="" style="width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:4px;display:block;background:#e8e4dc"
          onerror="this.style.background='#e8e4dc';this.src=''">
        <div style="font-size:0.68rem;line-height:1.3;margin-top:4px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${esc(b.title)}</div>
      </div>`;
    }).join("");
  } catch(e) {
    grid.innerHTML = '<span style="font-size:0.82rem;color:#e05">エラーが発生しました</span>';
  }
}

function selectDescBook(isbn, title) {
  document.getElementById("descIsbn").value = isbn;
  document.getElementById("descSearchResults").style.display = "none";
  document.getElementById("descTitleSearch").value = "";
  const info = document.getElementById("descBookInfo");
  info.textContent = `📖 ${title}`;
  info.style.display = "block";
  lookupBookAwards(isbn);
}

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
      lookupBookAwards(isbn);
      if (book.description) {
        document.getElementById("descText").value = book.description;
        document.getElementById("descCount").textContent = `（${book.description.length}/600文字）`;
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
      document.getElementById("descCount").textContent = "（0/600文字）";
      document.getElementById("descBookInfo").style.display = "none";
      loadNoBooksReview();
      setTimeout(() => { msg.textContent = ""; }, 3000);
    } else {
      const err = await res.json().catch(() => ({}));
      msg.textContent = "❌ 保存失敗: " + (err.error || res.status);
    }
  } catch(e) {
    msg.textContent = "❌ 通信エラー";
  }
}

// ===== 受賞作一覧 =====
let _currentAward = "";
let _allAwardBooks = [];

function filterAwardBooks() {
  const q = (document.getElementById("awardSearch")?.value || "").trim().toLowerCase();
  const books = q
    ? _allAwardBooks.filter(b =>
        (b.title || "").toLowerCase().includes(q) ||
        (b.author || "").toLowerCase().includes(q))
    : _allAwardBooks;
  _renderAwardBooks(books, q);
}

function _renderAwardBooks(books, query) {
  const list = document.getElementById("awardBooksList");
  if (!list) return;
  if (!books.length) {
    list.innerHTML = `<div style="color:#aaa;font-size:0.9rem;padding:20px 0;text-align:center">${query ? "該当する作品がありません" : "受賞作データがありません"}</div>`;
    return;
  }
  const byYear = {};
  for (const b of books) {
    const k = `${b.award_year}_${b.award}`;
    if (!byYear[k]) byYear[k] = { award: b.award, year: b.award_year, no: b.award_no, books: [] };
    byYear[k].books.push(b);
  }
  const groups = Object.values(byYear).sort((a, b) => b.year - a.year || b.no - a.no);
  list.innerHTML = groups.map(g => `
    <div style="border:1px solid #e8e8e8;border-radius:10px;padding:12px 14px;background:#fff">
      <div style="font-size:0.78rem;color:#888;margin-bottom:6px">
        ${esc(g.award)} 第${g.no}回（${g.year}年）
      </div>
      ${g.books.map(b => `
        <div style="display:flex;align-items:center;gap:10px;margin-top:${g.books.length > 1 ? "8px" : "0"}">
          <div style="flex:1">
            <div style="font-size:0.95rem;font-weight:600;color:#222">${esc(b.title)}</div>
            <div style="font-size:0.82rem;color:#666;margin-top:2px">${esc(b.author)}</div>
          </div>
          ${b.in_library
            ? `<span style="font-size:0.72rem;background:#e8f5e9;color:#2e7d32;padding:3px 8px;border-radius:12px;white-space:nowrap;cursor:pointer"
                 onclick="switchToBooksAndSearch('${esc(b.title).replace(/'/g,"\\'")}')">📖 蔵書あり</span>`
            : `<span style="font-size:0.72rem;background:#f5f5f5;color:#aaa;padding:3px 8px;border-radius:12px;white-space:nowrap">未所蔵</span>`
          }
        </div>`).join("")}
    </div>`).join("");
}

async function loadAwardBooks(award) {
  _currentAward = award || "";
  const list = document.getElementById("awardBooksList");
  if (!list) return;
  list.innerHTML = '<div style="color:#aaa;font-size:0.9rem;padding:20px 0;text-align:center">読み込み中…</div>';
  try {
    const url = award ? `/api/award-books?award=${encodeURIComponent(award)}` : "/api/award-books";
    const res = await fetch(url);
    const books = await res.json();
    _allAwardBooks = books;
    const q = (document.getElementById("awardSearch")?.value || "").trim().toLowerCase();
    _renderAwardBooks(q ? books.filter(b => (b.title||"").toLowerCase().includes(q)||(b.author||"").toLowerCase().includes(q)) : books, q);
  } catch(e) {
    list.innerHTML = `<div style="color:#c44;font-size:0.9rem;padding:20px 0;text-align:center">読み込みエラー: ${e.message}</div>`;
  }
}

async function initAwardsTab() {
  const filterRow = document.getElementById("awardFilterRow");
  if (!filterRow || filterRow.dataset.loaded) return;
  filterRow.dataset.loaded = "1";
  try {
    const res = await fetch("/api/award-books/awards");
    const awards = await res.json();
    const all = [{ award: "すべて", count: awards.reduce((s, a) => s + a.count, 0) }, ...awards];
    filterRow.innerHTML = all.map(a => `
      <button class="award-filter-btn${a.award === "すべて" ? " active" : ""}"
        data-award="${a.award === "すべて" ? "" : a.award}"
        onclick="selectAwardFilter(this)"
        style="padding:5px 12px;border-radius:16px;border:1px solid #ccc;background:${a.award==="すべて"?"#3d6b4f":"#fff"};color:${a.award==="すべて"?"#fff":"#444"};font-size:0.8rem;cursor:pointer">
        ${a.award}（${a.count}）
      </button>`).join("");
  } catch(e) {}
  loadAwardBooks("");
}

function selectAwardFilter(btn) {
  document.querySelectorAll(".award-filter-btn").forEach(b => {
    b.style.background = "#fff"; b.style.color = "#444";
    b.classList.remove("active");
  });
  btn.style.background = "#3d6b4f"; btn.style.color = "#fff";
  btn.classList.add("active");
  const resetBar = document.getElementById("awardResetBar");
  if (resetBar) resetBar.style.display = btn.dataset.award ? "block" : "none";
  loadAwardBooks(btn.dataset.award);
}

function resetAwardFilter() {
  const allBtn = document.querySelector('.award-filter-btn[data-award=""]');
  if (allBtn) selectAwardFilter(allBtn);
}

// 受賞作タブが開かれたときに初期化
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('.tab-btn[data-tab="awards"]').forEach(btn => {
    btn.addEventListener("click", () => setTimeout(initAwardsTab, 0));
  });
});

// ===== 操作ログ（管理者） =====

async function loadAuditLog() {
  const el = document.getElementById("auditLogContent");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  try {
    const res = await fetch("/api/admin/audit-log", { headers: { "X-Password": boardPassword } });
    if (!res.ok) { el.innerHTML = '<div style="color:#c44;padding:12px">取得エラー</div>'; return; }
    const rows = await res.json();
    if (!rows.length) { el.innerHTML = '<div style="color:#aaa;padding:12px">ログなし</div>'; return; }
    el.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:0.8rem">
        <thead><tr style="background:#f0f0f0;text-align:left">
          <th style="padding:6px 8px;border-bottom:1px solid #ddd;white-space:nowrap">日時</th>
          <th style="padding:6px 8px;border-bottom:1px solid #ddd">操作</th>
          <th style="padding:6px 8px;border-bottom:1px solid #ddd">対象</th>
          <th style="padding:6px 8px;border-bottom:1px solid #ddd">詳細</th>
          <th style="padding:6px 8px;border-bottom:1px solid #ddd">IP</th>
        </tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr style="border-bottom:1px solid #f5f5f5">
              <td style="padding:6px 8px;color:#888;white-space:nowrap">${esc(r.created_at)}</td>
              <td style="padding:6px 8px;font-weight:600">${esc(r.action)}</td>
              <td style="padding:6px 8px;color:#555">${esc(r.target || "")}</td>
              <td style="padding:6px 8px;color:#888">${esc(r.detail || "")}</td>
              <td style="padding:6px 8px;color:#aaa;font-size:0.75rem">${esc(r.ip || "")}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch(e) {
    el.innerHTML = `<div style="color:#c44;padding:12px">エラー: ${e.message}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('.board-tab[data-btab="auditlog"]').forEach(btn => {
    btn.addEventListener("click", () => loadAuditLog());
  });
});

// ===== 招待コード管理（管理者） =====

async function loadInviteCodes() {
  const el = document.getElementById("inviteCodesList");
  if (!el) return;
  el.innerHTML = '<div class="loading">読み込み中…</div>';
  try {
    const res = await fetch("/api/admin/invite-codes", { headers: { "X-Password": boardPassword } });
    if (!res.ok) { el.innerHTML = '<div style="color:#c44;padding:12px">取得エラー</div>'; return; }
    const codes = await res.json();
    if (!codes.length) { el.innerHTML = '<div style="color:#aaa;padding:12px">発行済みコードなし</div>'; return; }
    el.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
        <thead><tr style="background:#f0f0f0;text-align:left">
          <th style="padding:7px 8px;border-bottom:1px solid #ddd">コード</th>
          <th style="padding:7px 8px;border-bottom:1px solid #ddd">メモ</th>
          <th style="padding:7px 8px;border-bottom:1px solid #ddd">有効期限</th>
          <th style="padding:7px 8px;border-bottom:1px solid #ddd">使用状況</th>
          <th style="padding:7px 8px;border-bottom:1px solid #ddd">発行日</th>
          <th style="padding:7px 8px;border-bottom:1px solid #ddd"></th>
        </tr></thead>
        <tbody>
          ${codes.map(c => `
            <tr style="border-bottom:1px solid #f0f0f0">
              <td style="padding:7px 8px;font-family:monospace;font-size:0.95rem;font-weight:600;letter-spacing:0.08em">${esc(c.code)}</td>
              <td style="padding:7px 8px;color:#666">${esc(c.note || "—")}</td>
              <td style="padding:7px 8px;color:#666">${c.expires_at || "無期限"}</td>
              <td style="padding:7px 8px">
                ${c.used_room
                  ? `<span style="color:#2e7d32;font-size:0.8rem">✅ ${esc(c.used_room)}（${c.used_at || ""}）</span>`
                  : `<span style="color:#aaa;font-size:0.8rem">未使用</span>`}
              </td>
              <td style="padding:7px 8px;color:#888">${c.created_at}</td>
              <td style="padding:7px 8px">
                ${!c.used_room ? `<button onclick="deleteInviteCode(${c.id})" style="font-size:0.75rem;padding:3px 8px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#c44;cursor:pointer">削除</button>` : ""}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch(e) {
    el.innerHTML = `<div style="color:#c44;padding:12px">エラー: ${e.message}</div>`;
  }
}

async function issueInviteCodes() {
  const count   = parseInt(document.getElementById("inviteCount")?.value || "1");
  const note    = document.getElementById("inviteNote")?.value || "";
  const expires = document.getElementById("inviteExpires")?.value || "";
  const resEl   = document.getElementById("inviteIssueResult");
  resEl.textContent = "発行中…";
  try {
    const res = await fetch("/api/admin/invite-codes", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Password": boardPassword },
      body: JSON.stringify({ count, note, expires_at: expires || null }),
    });
    const data = await res.json();
    if (!res.ok) { resEl.textContent = "❌ " + (data.error || "エラー"); return; }
    resEl.innerHTML = `✅ ${data.codes.length}件発行：<strong style="font-family:monospace;letter-spacing:0.08em">${data.codes.join("　")}</strong>`;
    loadInviteCodes();
  } catch(e) {
    resEl.textContent = "❌ 通信エラー";
  }
}

async function deleteInviteCode(id) {
  if (!confirm("このコードを削除しますか？")) return;
  await fetch(`/api/admin/invite-codes/${id}`, {
    method: "DELETE", headers: { "X-Password": boardPassword },
  });
  loadInviteCodes();
}

// 招待コードタブを開いたときに読み込む
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('.board-tab[data-btab="invitecodes"]').forEach(btn => {
    btn.addEventListener("click", () => loadInviteCodes());
  });
});

// ===== 受賞作DB管理（管理者） =====
async function loadAdminAwardBooks() {
  const list = document.getElementById("adminAwardList");
  const countEl = document.getElementById("awdCount");
  if (!list) return;
  const award = document.getElementById("awdFilterAward")?.value || "";
  const pw = boardPassword;
  list.innerHTML = '<div style="color:#aaa;padding:16px">読み込み中…</div>';
  try {
    const url = `/api/award-books/admin?award=${encodeURIComponent(award)}`;
    const res = await fetch(url, { headers: { "X-Password": pw } });
    if (!res.ok) { list.innerHTML = `<div style="color:#c44;padding:16px">取得エラー (${res.status})</div>`; return; }
    const books = await res.json();
    if (countEl) countEl.textContent = `${books.length}件`;
    if (!books.length) { list.innerHTML = '<div style="color:#aaa;padding:16px">登録データなし</div>'; return; }
    list.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
        <thead>
          <tr style="background:#f0f0f0;text-align:left">
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">賞名</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">回</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">年</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">タイトル</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">著者</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd">状態</th>
            <th style="padding:7px 8px;border-bottom:1px solid #ddd"></th>
          </tr>
        </thead>
        <tbody>
          ${books.map(b => `
            <tr style="border-bottom:1px solid #eee" id="awdrow-${b.id}">
              <td style="padding:6px 8px">${esc(b.award)}</td>
              <td style="padding:6px 8px;text-align:center">${b.award_no ?? "—"}</td>
              <td style="padding:6px 8px;text-align:center">${b.award_year ?? "—"}</td>
              <td style="padding:6px 8px;font-weight:500">${esc(b.title)}</td>
              <td style="padding:6px 8px">${esc(b.author || "—")}</td>
              <td style="padding:6px 8px">
                <span style="font-size:0.75rem;padding:2px 7px;border-radius:10px;background:${b.status==='確認済'?'#e8f5e9':'#fff8e1'};color:${b.status==='確認済'?'#2e7d32':'#f57f17'}">
                  ${esc(b.status)}
                </span>
              </td>
              <td style="padding:6px 8px">
                <button onclick="deleteAwardBook(${b.id})"
                  style="font-size:0.75rem;padding:3px 8px;background:#ffebee;color:#c62828;border:1px solid #ef9a9a;border-radius:5px;cursor:pointer">
                  削除
                </button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  } catch(e) {
    list.innerHTML = `<div style="color:#c44;padding:16px">エラー: ${e.message}</div>`;
  }
}

async function submitAwardBook() {
  const msg = document.getElementById("awdMsg");
  const award  = document.getElementById("awdAward")?.value?.trim();
  const title  = document.getElementById("awdTitle")?.value?.trim();
  const author = document.getElementById("awdAuthor")?.value?.trim();
  const year   = parseInt(document.getElementById("awdYear")?.value) || null;
  const no     = parseInt(document.getElementById("awdNo")?.value) || null;
  const status = document.getElementById("awdStatus")?.value || "確認済";
  if (!award || !title) { msg.textContent = "❌ 賞名とタイトルは必須です"; return; }
  msg.textContent = "送信中…";
  try {
    const res = await fetch("/api/award-books", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ password: boardPassword, award, title, author, award_year: year, award_no: no, status })
    });
    if (res.ok) {
      msg.textContent = "✅ 登録しました";
      document.getElementById("awdTitle").value = "";
      document.getElementById("awdAuthor").value = "";
      document.getElementById("awdYear").value = "";
      document.getElementById("awdNo").value = "";
      loadAdminAwardBooks();
      setTimeout(() => { msg.textContent = ""; }, 3000);
    } else {
      const err = await res.json().catch(() => ({}));
      msg.textContent = "❌ " + (err.error || res.status);
    }
  } catch(e) { msg.textContent = "❌ 通信エラー"; }
}

async function deleteAwardBook(id) {
  if (!confirm("この受賞作を削除しますか？")) return;
  const res = await fetch(`/api/award-books/${id}`, {
    method: "DELETE",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ password: boardPassword })
  });
  if (res.ok) {
    document.getElementById(`awdrow-${id}`)?.remove();
    const countEl = document.getElementById("awdCount");
    if (countEl) {
      const cur = parseInt(countEl.textContent) || 0;
      countEl.textContent = `${Math.max(0, cur-1)}件`;
    }
  }
}

// btab切替時に読み込み
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('.board-tab[data-btab="awarddb"]').forEach(btn => {
    btn.addEventListener("click", () => setTimeout(loadAdminAwardBooks, 0));
  });
});
