import fitz  # PyMuPDF
import os
import re
import math
from itertools import groupby
from collections import defaultdict
from datetime import datetime
FONT_PATH = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"

# =========================
# 定数・設定
INPUT_DIR = "input_pdfs"
OUTPUT_DIR = "output_pdfs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

RED = (1, 0, 0)
GREEN = (0, 1, 0)
PINK = (1, 0.8, 0.8)


# =========================
# 日本語チェックルール
# =========================

HEADING_WORDS = [
    "目次",
    "実験方法",
    "実験結果",
    "結果",
    "考察",
    "参考文献",
    "参考資料",
]

SUSPECT_REF_PATTERNS = [
    r"https?://",
    r"arxiv",
    r"未発表",
    r"投稿中",
    r"submitted",
]


WATCH_WORDS = [
    "定常偏差",
    "過渡応答",
    "オーバーシュート",
    "バックラッシュ",
    "バックラッシ",
    "PI制御",
    "P制御",
    "PI補償",
    "P補償",
    "PI 制御",
    "P 制御",
    "PI 補償",
    "P 補償",
    "PD",
    "PID",
    "式",
    "限界感度",
    "限界周期",
    "有効範囲",
]

HEADING_RE = re.compile(
    r"^\s*\d+(\.\d+)*\s+(" + "|".join(map(re.escape, HEADING_WORDS)) + r")"
)


REF_ITEM_PATTERN = re.compile(
    r"""^\s*(\[\d+\]|\d+\.|\d+\)|[-•‣]|\(\d+\))""",
    re.VERBOSE,
)


FIG_TABLE_RE = re.compile(
    r"(図|表|Fig\.?|Table\.?)\s*([0-9０-９]+)",
    re.IGNORECASE
)



# =========================
# 判定関数
# =========================

def is_suspect_reference(line):
    l = line.lower()
    return any(re.search(p, l) for p in SUSPECT_REF_PATTERNS)

def normalize_text(s):
    if not s:
        return ""
    s = s.replace("\u00a0", " ")   # NBSP
    s = s.replace("\u3000", " ")   # 全角スペース
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_kind(s):#図表の区別
    s = s.lower()
    if s in ("図", "fig", "fig."):
        return "figure"
    if s in ("表", "table", "table."):
        return "table"
    return s

def normalize_number(s):
    # 全角数字 → 半角数字
    trans = str.maketrans(
        "０１２３４５６７８９",
        "0123456789"
    )
    return s.translate(trans)

def clean_word(txt):
    txt = txt.strip()
    txt = txt.replace("，", ",").replace("．", ".")
    # 図表判定に不要な文字を削除
    txt = re.sub(r"[^\w図表]", "", txt)
    return txt



def group_words_by_line(words):
    lines = []

    for (block, line), group in groupby(
        words, key=lambda w: (w[5], w[6])
    ):
        group = list(group)
        line_text = "".join(w[4] for w in group)

        lines.append({
            "text": line_text,
            "words": group,
            "block": block,   # ← 重要
            "line": line,     # ← 重要
        })

    return lines



def toc_page_numbers_ok(page_numbers, check_first=5):
    """
    page_numbers: List[int]
    Returns: bool
    """
    if not page_numbers:
        return False

    nums = page_numbers[:check_first]

    # 全部同じ？
    if len(set(nums)) == 1:
        # 特に全部 1 はアウト
        if nums[0] == 1:
            return False

    return True

def check_toc(doc, max_pages=3):
    has_toc = False
    toc_page_numbers = []

    for page in doc[:max_pages]:
        blocks = page.get_text("blocks")

        for b in blocks:
            text = b[4]
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            for line in lines:
                # ① 目次見出し検出（ゆるめ）
                if re.search(r"(前半|後半)?レポート?\s*目次$", line):
                    has_toc = True
                    continue

                if not has_toc:
                    continue

                # ② 目次っぽい行のページ番号取得
                # 例: "1. 実験方法 ........ 3"
                m = re.search(r"(\d+)\s*$", line)
                if m:
                    toc_page_numbers.append(int(m.group(1)))

    # ページ番号がなければ判定不能 → NG
    if not toc_page_numbers:
        return has_toc, False

    page_numbers_ok = toc_page_numbers_ok(toc_page_numbers)


    return has_toc, page_numbers_ok

def count_figures_and_tables(fig_positions):
    """
    fig_positions:
        dict[(kind, num)] -> list of entries

    Returns:
        (figure_count, table_count)
    """
    figure_nums = {
        num for (kind, num) in fig_positions.keys()
        if kind == "figure"
    }

    table_nums = {
        num for (kind, num) in fig_positions.keys()
        if kind == "table"
    }

    return len(figure_nums), len(table_nums)


# =========================
# 描画ユーティリティ
# =========================
def valid_rect(r):
    if r is None:
        return False
    if math.isnan(r.x0) or math.isnan(r.y0):
        return False
    # 最小サイズを許容
    if (r.x1 - r.x0) < 0.5 or (r.y1 - r.y0) < 0.5:
        return False
    return True

def rect_center(rect):#四角の中心
    return (
        (rect.x0 + rect.x1) / 2,
        (rect.y0 + rect.y1) / 2,
    )

def distance(r1, r2):#四角同士の距離
    x1, y1 = rect_center(r1)
    x2, y2 = rect_center(r2)
    return math.hypot(x1 - x2, y1 - y2)

def draw_red_box(page, rect, width=1):
   if not valid_rect(rect):
        return
   page.draw_rect(rect, color=RED, width=width)

def draw_red_underline(page, rect, width=1):
    page.draw_line((rect.x0,rect.y1), (rect.x1,rect.y1), color=RED, width=width)

def draw_connections_same_page(doc, fig_positions):
    #print("FIG_POSITIONS KEYS:", fig_positions.keys())  # ★追加

    for (kind, num), entries in fig_positions.items():
        #print("ENTRY:", kind, num, entries)  # ★追加

        texts = [e for e in entries if e["role"] == "text"]
        figs  = [e for e in entries if e["role"] == "figure"]

        #print("  texts:", len(texts), "figs:", len(figs))  # ★追加

        if not texts or not figs:
            continue

        for f in figs:
            page = doc[f["page"]]
            fig_center = rect_center(f["rect"])

            for t in texts:
                if t["page"] != f["page"]:
                    continue

                text_center = rect_center(t["rect"])

                page.draw_line(
                    text_center,
                    fig_center,
                    color=(1, 0.8, 0.8),
                    width=0.5,
                )


def draw_japanese_on_cover_test(page, check_flags):
    page.insert_font(fontname="jp", fontfile=FONT_PATH)

    page.insert_text(
        (200, page.rect.height - 100),
        "あいうえおカキクケコ漢字テスト",
        fontsize=14,
        fontname="jp",
        color=(1, 0, 0),
    )


def draw_checklist_on_cover(page, check_flags):
    x = 200
    y = page.rect.height - 180
    line_h = 18
    page.insert_font(fontname="jp", fontfile=FONT_PATH)
    
    page.insert_text(
        (x, y - 20),
        "--- Auto check ---",
        fontsize=14,
        #fontname="helv",
        fontname="jp",
        color=(1, 0, 0),
    )

    for key, label in [
#        ("has_toc", "TOC　目次"),
        ("toc_page_numbers_ok", "TOC 　目次"),
        ("page_count", "Page 総ページ数"),
        ("figure_count", "Fig 図"),
        ("table_count", "Tab　表"),
        ("ref_count", "Ref　参考文献"),
    ]:

        value = check_flags[key]

        if isinstance(value, bool):
            mark = "OK" if value else "x"
            text = f"[{mark}] {label}"
            color = (0, 0.6, 0) if value else (1, 0, 0)
        else:
            text = f"[{value}] {label}"
            color = (0, 0.6, 0) if value > 1 else (1, 0, 0)


        page.insert_text(
            (x, y),
            text,
            fontsize=11,
            #fontname="helv",
            fontname="jp",
            color=color,
        )
        y += line_h



def check_toc_page_numbers_and_draw(page, max_check=5, right_ratio=0.75):
    """
    True: ページ番号OK
    False: 先頭 max_check 個が全部同じ → 怪しい
    right_ratio: 右端何％をページ番号領域とみなすか
    """

    raw = page.get_text("rawdict")
    page_width = page.rect.width

    nums = []
    num_rects = []

    for block in raw["blocks"]:
        for line in block.get("lines", []):
            chars = []
            for span in line.get("spans", []):
                chars.extend(span.get("chars", []))

            text = "".join(c["c"] for c in chars)

            for m in re.finditer(r"\d+", text):
                start, end = m.span()
                hit = chars[start:end]
                if not hit:
                    continue

                rect = fitz.Rect(hit[0]["bbox"])
                for c in hit[1:]:
                    rect |= fitz.Rect(c["bbox"])

                # --- 右端判定 ---
                if rect.x0 < page_width * right_ratio:
                    continue  # 左側 → 章番号などなので除外

                nums.append(int(m.group()))
                num_rects.append(rect)

    # --- 見つかったページ番号を全部囲む ---
    for r in num_rects:
        draw_red_box(page, r, width=0.8)

    # --- 判定 ---
    if len(nums) < max_check:
        return True  # 判断材料不足 → OK

    if len(set(nums[:max_check])) == 1:
        return False  # 全部同じ → 怪しい

    return True



def check_toc_and_draw(doc, max_pages=2):
    result = {
        "has_toc": False,
        "page_number_ok": True,
        "toc_page": None,
    }

    for page in doc[:max_pages]:
        blocks = page.get_text("blocks")

        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            clean = normalize_text(text)

            if "目次" in clean:
                # --- 目次ヒット ---
                result["has_toc"] = True
                result["toc_page"] = page.number

                rect = fitz.Rect(x0, y0, x1, y1)
                draw_red_box(page, rect, width=1)

                # ページ番号チェックもここで
                ok = check_toc_page_numbers_and_draw(page)
                result["page_number_ok"] = ok

                return result

    return result

def draw_watchword_underlines(page, words, width=1):
    count = 0
    for word in words:
        for r in page.search_for(word):
            box = fitz.Rect(
                r.x0 - 2,
                r.y0 - 1,
                r.x1 + 2,
                r.y1 + 1,
            )
            draw_red_underline(page, box, width=width)
            count += 1
    return count


def _draw_reference_entry(page, lines, rects, char_len_warn):
    if not rects:
        return

    rect = rects[0]
    for r in rects[1:]:
        rect |= r

    draw_red_box(page, rect, width=0.8)

    text = "".join(lines)
    clean_len = len(re.sub(r"\s+", "", text))

    if clean_len <= char_len_warn:
        page.insert_text(
            (rect.x0 - 12, rect.y1),
            "*",
            fontsize=16,
            fontname="helv",
            color=(1, 0, 0),
        )

def finalize_current_reference(
    page, current_lines, current_rects,
    seen_refs, char_len_warn
):
    key = normalize_reference_key(current_lines)
    if key in seen_refs:
        return False

    seen_refs.add(key)
    # ★★★ ここにデバッグ出力 ★★★
    ref_text = " ".join(current_lines)
    #print("[REF]", ref_text)#debug

    _draw_reference_entry(
        page,
        current_lines,
        current_rects,
        char_len_warn,
    )
    return True

def normalize_reference_key(lines):
    text = "".join(lines)
    text = re.sub(r"\s+", "", text)
    text = text.lower()
    return text[:200]  # 長すぎ防止


def check_references_and_draw(doc, char_len_warn=10):
    ref_count = 0
    references = []   # ← ★ 追加
    seen_refs = set()

    pages = doc[-2:] if len(doc) >= 2 else [doc[-1]]

    for page in pages:
        blocks = page.get_text("dict")["blocks"]

        in_references = False
        current_lines = []
        current_rects = []

        for block in blocks:
            if "lines" not in block:
                continue

            for line in block["lines"]:
                # 行テキストと bbox
                spans = line["spans"]
                line_text = "".join(s["text"] for s in spans).strip()

                if not line_text:
                    continue

                # --- 「参考文献」検出 ---
                if not in_references:
                    if re.search(r"参考文献", line_text):
                        in_references = True
                    continue

                # --- 文献番号の開始？ ---
                is_new_item = re.match(
                    r"^\s*(\[\d+\]|\d+\.|\d+\))", line_text
                )

                if is_new_item and current_lines:
                    if finalize_current_reference(
                        page, current_lines, current_rects,
                        seen_refs, char_len_warn
                    ):
                        ref_count += 1

                    current_lines = []
                    current_rects = []


                # 参考文献行として蓄積
                current_lines.append(line_text)

                for s in spans:
                    current_rects.append(fitz.Rect(s["bbox"]))
                    
        # 最後の文献
        if current_lines:
            if finalize_current_reference(
                page, current_lines, current_rects,
                seen_refs, char_len_warn
            ):
                ref_count += 1


        # ★ 参考文献は1ページ処理したら終了
        if in_references:
            break

    return ref_count, references

def pickup_fig_table_no_text(page):
    """
    本文中の「図1」「表2」などを検出
    role = "text"
    return: list of (kind, num, entry)
    """
    results = []

    raw = page.get_text("rawdict")
    blocks = page.get_text("dict")["blocks"]

    # --- block番号付き char 一覧 ---
    chars = []
    for block in raw["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    chars.append({
                        "c": ch["c"],
                        "bbox": ch["bbox"],
                        "block": block["number"],
                    })

    # --- block 単位で処理 ---
    for block in blocks:
        if "lines" not in block:
            continue

        block_chars = [c for c in chars if c["block"] == block["number"]]
        if not block_chars:
            continue

        text = "".join(c["c"] for c in block_chars)

        for m in FIG_TABLE_RE.finditer(text):
            kind = normalize_kind(m.group(1))
            num  = normalize_number(m.group(2))

            start, end = m.span()
            hit_chars = block_chars[start:end]
            if not hit_chars:
                continue

            rect = fitz.Rect(hit_chars[0]["bbox"])
            for c in hit_chars[1:]:
                rect |= fitz.Rect(c["bbox"])

            results.append(
                (kind, num, {
                    "page": page.number,
                    "rect": rect,
                    "role": "text",
                })
            )

    return results

def pickup_fig_table_no_caption(page):
    """
    図表キャプション中の「図1」「表2」を検出
    role = "figure"
    return: list of (kind, num, entry)
    """
    results = []

    raw = page.get_text("rawdict")

    for block in raw["blocks"]:
        if "lines" not in block:
            continue

        for line in block["lines"]:
            line_chars = []
            for span in line["spans"]:
                line_chars.extend(span.get("chars", []))

            if not line_chars:
                continue

            text = "".join(c["c"] for c in line_chars)

            for m in FIG_TABLE_RE.finditer(text):
                kind = normalize_kind(m.group(1))
                num  = normalize_number(m.group(2))

                start, end = m.span()
                hit_chars = line_chars[start:end]
                if not hit_chars:
                    continue

                rect = fitz.Rect(hit_chars[0]["bbox"])
                for c in hit_chars[1:]:
                    rect |= fitz.Rect(c["bbox"])

                results.append(
                    (kind, num, {
                        "page": page.number,
                        "rect": rect,
                        "role": "figure",
                    })
                )

    return results


def process_pages(doc, check_flags, stamp_datetime=True):
    """
    各ページ共通処理
    - 見出しチェック
    - 監視キーワードアンダーライン（3ページ目以降）
    - 処理日時スタンプ（左上）

    doc: fitz.Document
    check_flags: dict
    stamp_datetime: bool
    """

    # --- 処理日時文字列 ---
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    watchword_hits = 0

    for i, page in enumerate(doc):
        if i<2:
            continue # 1,2ページ目はスキップ
        # ========= 見出しチェック =========
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            for line in block.get("lines", []):
                spans = line["spans"]
                line_text = "".join(s["text"] for s in spans).strip()

                if HEADING_RE.match(line_text):
                    rect = fitz.Rect(spans[0]["bbox"])
                    for s in spans[1:]:
                        rect |= fitz.Rect(s["bbox"])

                    draw_red_box(page, rect, width=0.5)

                    # 行頭マーク
                    page.draw_rect(
                        fitz.Rect(rect.x0 - 10, rect.y0, rect.x0 - 4, rect.y1),
                        color=RED,
                        fill=(1, 1, 1),
                    )

        # ========= 監視キーワード（3ページ目以降） =========
        if i >= 2:
            watchword_hits += draw_watchword_underlines(
                page,
                WATCH_WORDS,
            )

        # ========= 処理日時スタンプ =========
        if stamp_datetime:
            page.insert_text(
                (12, 16),   # 左上
                f"--- AutoCheck {now_str} ---",
                fontsize=8,
                fontname="helv",
                color=(1.0, 0.5, 0.5),
            )

    check_flags["watchword_hits"] = watchword_hits


# =========================
# メイン処理
# =========================

def process_pdf(input_path, output_path):
    doc = fitz.open(input_path)

    # ---------- 全体チェックフラグ ----------
    check_flags = {
        "has_toc": False,
        "toc_page_numbers_ok": False,
        "page_count": len(doc),
        "figure_count": 0,
        "table_count": 0,
        "ref_count": 0,
    }


    # --- 目次チェック ---
    toc_result = check_toc_and_draw(doc)
    check_flags["has_toc"] = toc_result["has_toc"]
    check_flags["toc_page_numbers_ok"] = toc_result["page_number_ok"]
    


    # 全ページ走査で図表位置収集
    fig_positions = defaultdict(list)
    for page in doc:
        for kind, num, entry in pickup_fig_table_no_text(page):
            fig_positions[(kind, num)].append(entry)
            draw_red_box(page, entry["rect"], width=1)

        for kind, num, entry in pickup_fig_table_no_caption(page):
            fig_positions[(kind, num)].append(entry)

    # 全ページ走査が終わったあと
    fig_count, tab_count = count_figures_and_tables(fig_positions)
    check_flags["figure_count"] = fig_count
    check_flags["table_count"]  = tab_count

    draw_connections_same_page(doc, fig_positions)


    # --- 参考文献チェック ---
    ref_count, references = check_references_and_draw(doc)
    check_flags["ref_count"] = ref_count


    # ---------- 各ページ処理 ----------
    process_pages(doc, check_flags)
   
    # ---------- 表紙メッセージ（下部） ----------
    cover = doc[0]
    draw_checklist_on_cover(cover, check_flags)

    doc.save(output_path)
    doc.close()

# =========================
# 複数ファイル一括処理
# =========================

def main():
    for f in os.listdir(INPUT_DIR):
        if f.lower().endswith(".pdf"):
            print("Processing:", f)
            process_pdf(
                os.path.join(INPUT_DIR, f),
                os.path.join(OUTPUT_DIR, f),
            )
    print("All done.")

if __name__ == "__main__":
    main()
