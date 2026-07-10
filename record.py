#!/usr/bin/env python3
"""
aki-mind 記録スクリプト
Claudeが会話から自動で呼び出す。

使い方:
  python3 record.py "今日嫌な顔された"
  python3 record.py "ブログ書いた" --url https://example.com --title "記事タイトル"
  python3 record.py "メモ: 今日気づいたこと"

必要な設定:
  環境変数 GITHUB_TOKEN にGitHub Personal Access Tokenを設定するか、
  ~/.aki_config に書いておく（書式: GITHUB_TOKEN=ghp_xxxx）
"""

import sys, os, json, base64, re, urllib.request, urllib.error
from datetime import datetime

# ── 設定 ──
REPO = "zenmode-aki/aki-mind"
FILE = "journey-log.json"

def get_token():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        config = os.path.expanduser("~/.aki_config")
        if os.path.exists(config):
            for line in open(config):
                if line.startswith("GITHUB_TOKEN="):
                    token = line.strip().split("=", 1)[1]
    return token

# ── GitHub API ──
def gh_get(path, token):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "aki-record"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def gh_put(path, body_dict, token):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body_dict).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "User-Agent": "aki-record"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def read_json(token):
    res = gh_get(f"contents/{FILE}", token)
    raw = base64.b64decode(res["content"]).decode("utf-8")
    return json.loads(raw), res["sha"]

def write_json(data, sha, message, token):
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode()
    gh_put(f"contents/{FILE}", {
        "message": message,
        "content": encoded,
        "sha": sha
    }, token)

# ── 自然言語パーサー ──
FAILURE_PATTERNS = [
    (["嫌な顔", "冷たくされ", "無視され"], "😬", "嫌な顔をされた", 1),
    (["断られ", "拒否され", "NOと言われ"], "🙅", "頼んで断られた", 2),
    (["恥ずかし", "赤面", "やばかった"], "😳", "恥ずかしかった", 1),
    (["失敗し", "ミスし", "うまくできなかった", "やらかし"], "💦", "失敗した", 1),
    (["挑戦し", "試みた", "やってみた"], "⚡", "挑戦してみた", 1),
    (["正直に言", "本音を言", "勇気を出し"], "💬", "正直に伝えた", 1),
    (["緊張し", "ドキドキし"], "💓", "緊張したけどやった", 1),
]

BLOG_KEYWORDS = ["ブログ", "記事", "投稿", "書いた", "公開した"]
LINK_KEYWORDS = ["リンク", "URL", "シェア", "共有"]
ACH_KEYWORDS  = ["達成", "完了", "できた", "終わった", "合格"]

def parse_text(text, url=None, title=None):
    text_lower = text

    if url or any(k in text_lower for k in BLOG_KEYWORDS + LINK_KEYWORDS):
        return {
            "type": "blog" if any(k in text_lower for k in BLOG_KEYWORDS) else "link",
            "title": title or re.sub(r'https?://\S+', '', text).strip() or "リンク",
            "url": url or re.search(r'https?://\S+', text_lower, re.I)and re.search(r'https?://\S+', text_lower, re.I).group(0) or "",
            "description": text if not url else ""
        }

    if any(k in text_lower for k in ACH_KEYWORDS):
        return {"type": "achievement", "title": text}

    for keywords, icon, name, pts in FAILURE_PATTERNS:
        if any(k in text_lower for k in keywords):
            return {"type": "failure", "text": text, "name": name, "icon": icon, "points": pts}

    return {"type": "memo", "text": text}

# ── 今日のステージを取得/作成 ──
def get_or_create_today(data):
    today = datetime.now().strftime("%Y-%m-%d")
    for s in data.get("stages", []):
        if s.get("date") == today:
            s["status"] = "current"
            return s, False

    for s in data.get("stages", []):
        if s.get("status") == "current":
            s["status"] = "done"

    day_num = max((s.get("dayNumber", 0) for s in data.get("stages", [])), default=0) + 1
    emojis = ["📅","🌱","⚡","🌙","☀️","🔥","💫","🌿","🎯","✨"]
    new_stage = {
        "date": today,
        "dayNumber": day_num,
        "title": f"Day {day_num}",
        "emoji": emojis[day_num % len(emojis)],
        "status": "current",
        "items": []
    }
    data.setdefault("stages", []).append(new_stage)
    return new_stage, True

# ── メイン ──
def main():
    import argparse
    parser = argparse.ArgumentParser(description="aki-mind 記録ツール")
    parser.add_argument("text", nargs="+", help="記録する内容")
    parser.add_argument("--url",   default="", help="URL（ブログ・リンク用）")
    parser.add_argument("--title", default="", help="タイトル（ブログ・リンク用）")
    parser.add_argument("--pts",   type=int, default=0, help="失敗ポイント（省略時は自動）")
    args = parser.parse_args()

    text  = " ".join(args.text)
    token = get_token()

    if not token:
        print("❌ GITHUB_TOKEN が見つかりません。")
        print("   ~/.aki_config に「GITHUB_TOKEN=ghp_xxxx」と書いてください。")
        sys.exit(1)

    print(f"📖 journey-log.json を読み込み中...")
    try:
        data, sha = read_json(token)
    except urllib.error.HTTPError as e:
        print(f"❌ GitHub API エラー: {e.code} {e.reason}")
        sys.exit(1)

    stage, is_new = get_or_create_today(data)
    item = parse_text(text, args.url or None, args.title or None)
    if args.pts:
        item["points"] = args.pts

    stage["items"].append(item)

    type_label = {"memo":"メモ","failure":"失敗","blog":"ブログ","link":"リンク","achievement":"達成"}.get(item["type"], item["type"])
    commit_msg = f"[{type_label}] {text[:40]}"

    print(f"✍️  記録中: {item}")
    write_json(data, sha, commit_msg, token)

    print(f"\n✅ 記録完了！")
    print(f"   種類: {type_label}")
    print(f"   内容: {text}")
    if item.get("points"):
        print(f"   失敗ポイント: +{item['points']}pt")
    if is_new:
        print(f"   → 新しいステージ「Day {stage['dayNumber']}」を作成しました")
    print(f"\n🗺️  確認: https://zenmode-aki.github.io/aki-mind/journey.html")

if __name__ == "__main__":
    main()
