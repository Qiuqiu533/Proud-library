import logging

logger = logging.getLogger(__name__)
import os
import json

# static/app.js・static/style.css を変更した回はこの値も一緒にインクリメントする。
# style.css/app.js は Cache-Control: immutable（1年）で配信されるため、URLに
# ?v= を付けてクエリ文字列ごと変えることで、Service Workerのキャッシュ更新を
# 待たずに新しいCSS/JSを確実に配信する（2026-07-05追加）。
STATIC_VERSION = "25"

# ── ジャンル別蔵書データ（Excelから事前生成）──────────────────────────────
_GENRE_MAP_PATH = os.path.join(os.path.dirname(__file__), "static", "genre_map.json")
try:
    with open(_GENRE_MAP_PATH, encoding="utf-8") as _f:
        GENRE_MAP = json.load(_f)
except Exception:
    GENRE_MAP = {}

# ── 定数 ────────────────────────────────────────────────────────────────
LIBRARY_CODE = "0011"
LIBRARYLIFE_BASE = "https://www.librarylife.net"
OPENBD_API = "https://api.openbd.jp/v1/get"
NDL_THUMB = "https://ndlsearch.ndl.go.jp/thumbnail/{isbn}.jpg"

LIBRARY_INFO = {
    "name": "プラウド船橋コミュニティ図書館",
    "hours": [
        {"day": "月〜金", "time": "10:00〜18:00"},
        {"day": "土・日・祝", "time": "10:00〜17:00"},
    ],
    "closed": "第2・第4水曜日、年末年始",
    "location": "千葉県船橋市北本町1-12-17 プラウド船橋クラブハウス内",
    "zip": "〒273-0864",
    "note": "最新情報はlibrarlife.netをご確認ください。",
}

_ADMIN_PASSWORD_ENV    = os.environ.get("ADMIN_PASSWORD",    "")
_RESIDENT_PASSWORD_ENV = os.environ.get("RESIDENT_PASSWORD", "")
_BOARD_PASSWORD_ENV    = os.environ.get("BOARD_PASSWORD",    "")
_RESEND_API_KEY        = os.environ.get("RESEND_API_KEY",       "")
_APP_BASE_URL          = os.environ.get("APP_BASE_URL",         "https://proud-library.onrender.com")
_BREVO_SMTP_PASSWORD   = os.environ.get("BREVO_SMTP_PASSWORD",  "")
_BREVO_SMTP_USER       = os.environ.get("BREVO_SMTP_USER",      "")
_NOTIFY_FROM_EMAIL     = os.environ.get("NOTIFY_FROM_EMAIL",    "")
# 招待コード必須フラグ: 環境変数 INVITE_REQUIRED=1 で有効化
INVITE_REQUIRED        = os.environ.get("INVITE_REQUIRED", "0") == "1"

# 起動時に必須環境変数の未設定を警告
for _env_key, _env_val in [
    ("ADMIN_PASSWORD", _ADMIN_PASSWORD_ENV),
    ("RESIDENT_PASSWORD", _RESIDENT_PASSWORD_ENV),
    ("BOARD_PASSWORD", _BOARD_PASSWORD_ENV),
]:
    if not _env_val:
        logger.warning(f"[WARNING] 環境変数 {_env_key} が未設定です。Renderのダッシュボードで設定してください。")

_KANA_ROWS = {
    "あ": "あいうえおアイウエオ",
    "か": "かきくけこがぎぐげごカキクケコガギグゲゴ",
    "さ": "さしすせそざじずぜぞサシスセソザジズゼゾ",
    "た": "たちつてとだぢづでどタチツテトダヂヅデド",
    "な": "なにぬねのナニヌネノ",
    "は": "はひふへほばびぶべぼぱぴぷぺぽハヒフヘホバビブベボパピプペポ",
    "ま": "まみむめもマミムメモ",
    "や": "やゆよャュョヤユヨ",
    "ら": "らりるれろラリルレロ",
    "わ": "わをんヲンワ",
}

NDC_TO_GENRE = {
    # 日本文学
    "913": "文芸小説", "915": "文芸小説",
    "914": "エッセイ・評論", "916": "エッセイ・評論", "917": "エッセイ・評論",
    "911": "エッセイ・評論",
    "912": "エッセイ・評論",
    "9131": "時代小説・歴史小説",
    # ミステリ
    "936": "ミステリ・推理",
    # 翻訳小説
    "920": "翻訳小説", "921": "翻訳小説", "922": "翻訳小説", "923": "翻訳小説",
    "930": "翻訳小説", "931": "翻訳小説", "932": "翻訳小説", "933": "翻訳小説",
    "934": "翻訳小説", "935": "翻訳小説", "937": "翻訳小説", "938": "翻訳小説",
    "940": "翻訳小説", "941": "翻訳小説", "942": "翻訳小説", "943": "翻訳小説",
    "950": "翻訳小説", "951": "翻訳小説", "953": "翻訳小説", "955": "翻訳小説",
    "960": "翻訳小説", "961": "翻訳小説", "963": "翻訳小説",
    "970": "翻訳小説", "971": "翻訳小説", "973": "翻訳小説",
    "980": "翻訳小説", "981": "翻訳小説", "983": "翻訳小説",
    "990": "翻訳小説", "993": "翻訳小説",
    # 絵本・児童
    "726": "絵本・児童書", "E": "絵本・児童書",
    "Y8": "絵本・児童書", "Y81": "絵本・児童書", "Y82": "絵本・児童書",
    "Y9": "児童文学", "Y91": "児童文学", "Y92": "児童文学",
    # 自己啓発・ビジネス
    "159": "実用・ハウツー", "336": "実用・ハウツー", "335": "実用・ハウツー",
    "320": "実用・ハウツー", "330": "実用・ハウツー", "331": "実用・ハウツー",
    "338": "実用・ハウツー", "141": "実用・ハウツー", "143": "実用・ハウツー",
    "145": "実用・ハウツー", "146": "実用・ハウツー", "370": "実用・ハウツー",
    # 健康・医療
    "490": "実用・ハウツー", "491": "実用・ハウツー", "492": "実用・ハウツー",
    "493": "実用・ハウツー", "494": "実用・ハウツー", "495": "実用・ハウツー",
    "496": "実用・ハウツー", "497": "実用・ハウツー", "498": "実用・ハウツー",
    # 料理・生活
    "596": "実用・ハウツー", "590": "実用・ハウツー", "591": "実用・ハウツー",
    "593": "実用・ハウツー", "597": "実用・ハウツー", "598": "実用・ハウツー",
    # 歴史・伝記
    "210": "歴史・伝記", "211": "歴史・伝記", "212": "歴史・伝記",
    "213": "歴史・伝記", "214": "歴史・伝記", "215": "歴史・伝記",
    "216": "歴史・伝記", "217": "歴史・伝記", "218": "歴史・伝記",
    "219": "歴史・伝記", "230": "歴史・伝記",
    "280": "歴史・伝記", "281": "歴史・伝記", "289": "歴史・伝記",
    # 社会・ノンフィクション
    "300": "エッセイ・評論", "304": "エッセイ・評論",
    "360": "エッセイ・評論", "361": "エッセイ・評論",
    "316": "エッセイ・評論",
}

KEYWORD_GENRE = [
    (["ミステリ","推理","刑事","探偵","殺人","犯罪","謎解き","サスペンス","トリック","密室","アリバイ"], "ミステリ・推理"),
    (["時代小説","武士","侍","江戸","幕末","忍者","剣客","剣士","藩","将軍","大名","お奉行","岡っ引き","鬼平","池波"], "時代小説・歴史小説"),
    (["戦国","信長","秀吉","家康","源氏","平家","幕府","藩士","勤皇","明治維新"], "時代小説・歴史小説"),
    (["SF","宇宙","ロボット","人工知能","タイムスリップ","タイムトラベル","サイバー","ディストピア","クローン"], "ファンタジー・SF"),
    (["ファンタジー","魔法","魔王","勇者","異世界","竜","ドラゴン","エルフ","精霊","魔女","魔術師"], "ファンタジー・SF"),
    (["ホラー","怪談","心霊","幽霊","呪い","恐怖","怖い","オカルト","超自然","霊","怨霊","妖怪"], "ホラー・怪談"),
    (["恋愛","ラブ","片思い","告白","恋人","青春","青い","初恋","純愛","ロマンス"], "恋愛・青春"),
    (["高校生","大学生","学園","部活","友情","青春","思春期","卒業","入学","甲子園"], "恋愛・青春"),
    (["コミックエッセイ","マンガエッセイ","育児マンガ","介護マンガ"], "エッセイ・評論"),
    (["絵本","えほん","ピクチャーブック"], "絵本・児童書"),
    (["児童文学","子ども向け","読み聞かせ","お話絵本"], "児童文学"),
    (["伝記","一代記","生涯","列伝","ノンフィクション","実話","ルポ","ドキュメント"], "歴史・伝記"),
    (["昭和史","平成史","近代史","現代史","太平洋戦争","戦争体験"], "歴史・伝記"),
    (["料理","レシピ","クッキング","おかず","献立","お菓子作り","パン作り"], "実用・ハウツー"),
    (["健康","ダイエット","医療","病気","症状","治療","養生","血圧","糖尿","介護","認知症"], "実用・ハウツー"),
    (["ビジネス","仕事術","マネジメント","リーダーシップ","起業","投資","株式","マーケティング","経営戦略"], "実用・ハウツー"),
    (["自己啓発","習慣","成功法則","メンタル","マインドセット","思考法","モチベーション"], "実用・ハウツー"),
]


def get_setting(key, default=""):
    """settings テーブルから値を取得。なければ default を返す。"""
    from database import get_con, fetchone
    try:
        con = get_con()
        row = fetchone(con, "SELECT value FROM settings WHERE key=?", (key,))
        con.close()
        if row:
            return row["value"]
    except Exception:
        pass
    return default


def get_admin_password():
    return get_setting("admin_password", _ADMIN_PASSWORD_ENV)


def get_resident_password():
    return get_setting("resident_password", _RESIDENT_PASSWORD_ENV)


def get_board_password():
    return get_setting("board_password", _BOARD_PASSWORD_ENV)


def check_password(provided: str, role: str) -> bool:
    """タイミング攻撃に耐性のある定数時間パスワード比較。
    role: "admin" | "board" | "resident"
    """
    import hmac
    getters = {
        "admin":    get_admin_password,
        "board":    get_board_password,
        "resident": get_resident_password,
    }
    expected = getters.get(role, lambda: "")()
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())