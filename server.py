import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

PORT = 8989
HOST = "127.0.0.1"

# 灰名单：忽略知名成熟平台、社交媒体、搜索引擎等
GREYLIST = {
    "google.com", "github.com", "youtube.com", "twitter.com", "x.com",
    "reddit.com", "producthunt.com", "ycombinator.com", "medium.com",
    "linkedin.com", "apple.com", "amazon.com", "wikipedia.org", "t.co",
    "bit.ly", "instagram.com", "facebook.com", "tiktok.com", "discord.com",
    "discord.gg", "substack.com", "notion.site", "loom.com", "figma.com",
    "microsoft.com", "techcrunch.com", "theverge.com", "bloomberg.com",
    "forbes.com", "wired.com", "news.ycombinator.com", "imgur.com"
}

# 常见平台二级域名识别
PAAS_DOMAINS = ("vercel.app", "lovable.app", "streamlit.app", "replit.app", "pages.dev", "webflow.io")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 内存缓存域名年龄，避免重复请求
DOMAIN_CACHE = {}

def extract_domain(url):
    """从 URL 中解析出纯主域名"""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if not netloc or "." not in netloc:
            return None
        # 排除灰名单
        for grey in GREYLIST:
            if netloc == grey or netloc.endswith("." + grey):
                return None
        return netloc
    except Exception:
        return None

def fetch_domain_age(domain):
    """通过免费 RDAP 协议查询域名注册年龄（天数）"""
    if not domain:
        return None, "未知"

    # 检查缓存
    if domain in DOMAIN_CACHE:
        return DOMAIN_CACHE[domain]

    # 特殊 PaaS 平台处理
    for paas in PAAS_DOMAINS:
        if domain.endswith(paas):
            res = (7, "⚡ 极速上线 (PaaS子域)")
            DOMAIN_CACHE[domain] = res
            return res

    url = f"https://rdap.org/domain/{urllib.parse.quote(domain)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            events = data.get("events", [])
            for ev in events:
                if ev.get("eventAction") == "registration":
                    date_str = ev.get("eventDate")
                    # 解析 ISO 时间
                    created_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    now_dt = datetime.now(timezone.utc)
                    age_days = (now_dt - created_dt).days
                    if age_days <= 30:
                        tag = "🔥 新上线 (≤30天)"
                    elif age_days <= 90:
                        tag = "🌱 早期项目 (≤90天)"
                    elif age_days <= 365:
                        tag = "🌿 成长期 (<1年)"
                    else:
                        tag = f"🏛️ 成熟站 ({age_days//365}年)"
                    res = (age_days, tag)
                    DOMAIN_CACHE[domain] = res
                    return res
    except Exception:
        pass

    res = (None, "⚪ 查无年限")
    DOMAIN_CACHE[domain] = res
    return res

def fetch_rss_feed(query):
    """通过 Google News RSS 语法免 API 抓取搜索结果"""
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    items = []
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            content = resp.read().decode("utf-8")
            root = ET.fromstring(content)
            for item in root.findall(".//item")[:20]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pubDate = item.find("pubDate").text if item.find("pubDate") is not None else ""
                description = item.find("description").text if item.find("description") is not None else ""
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pubDate,
                    "desc": description
                })
    except Exception as e:
        pass
    return items

def scan_twitter(time_range="3d", min_faves=0, custom_query=""):
    """渠道 1: 扫描 X/Twitter (支持时间跨度、高赞爆款模式与自定义词)"""
    time_filter = f"when:{time_range}" if time_range else "when:3d"

    if custom_query:
        query_core = custom_query
    elif min_faves >= 300:
        query_core = '("just launched" OR "just shipped" OR "introducing" OR "built this") "http"'
    else:
        query_core = '("just launched" OR "introducing" OR "built this tool") "http"'

    query = f'site:x.com ({query_core}) {time_filter}'
    raw_items = fetch_rss_feed(query)
    results = []
    for item in raw_items:
        title = item["title"].replace(" - Twitter", "").replace(" - X", "")
        found_urls = re.findall(r'https?://[^\s<>"\'\)]+', item["desc"] + " " + item["title"])
        target_domain = None
        target_url = item["link"]
        for u in found_urls:
            d = extract_domain(u)
            if d:
                target_domain = d
                target_url = u
                break

        if not target_domain:
            domain_matches = re.findall(r'\b[a-zA-Z0-9-]+\.(?:com|io|ai|co|app|dev|sh|org|tools|net)\b', item["title"])
            for dm in domain_matches:
                if dm.lower() not in GREYLIST:
                    target_domain = dm.lower()
                    target_url = f"https://{target_domain}"
                    break

        if target_domain:
            results.append({
                "channel": "Twitter / X",
                "badge_color": "bg-sky-500",
                "title": title,
                "domain": target_domain,
                "url": target_url,
                "source_url": item["link"],
                "pub_date": item["pubDate"],
                "min_faves": min_faves
            })
    return results

def scan_hackernews(time_range="1d", min_faves=0, custom_query=""):
    """渠道 2: 扫描 Hacker News (支持点赞积分阈值与24h时间窗口)"""
    hours = 24 if time_range == "1d" else (72 if time_range == "3d" else 168)
    cutoff_ts = int(datetime.now(timezone.utc).timestamp()) - (hours * 3600)

    filters = [f"created_at_i>{cutoff_ts}"]
    # 如果设置过高导致无数据，做智能软门槛
    if min_faves >= 500:
        filters.append("points>=50")
    elif min_faves > 0:
        filters.append(f"points>={min(min_faves, 30)}")

    num_filter_str = ",".join(filters)
    query_param = f"&query={urllib.parse.quote(custom_query)}" if custom_query else ""
    url = f"https://hn.algolia.com/api/v1/search_by_date?tags=show_hn&numericFilters={num_filter_str}&hitsPerPage=25{query_param}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    results = []
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for hit in data.get("hits", []):
                external_url = hit.get("url")
                domain = extract_domain(external_url)
                if domain:
                    pts = hit.get("points", 0)
                    results.append({
                        "channel": "Show HN",
                        "badge_color": "bg-orange-500",
                        "title": f"[{pts} pts] {hit.get('title', '')}",
                        "domain": domain,
                        "url": external_url,
                        "source_url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                        "pub_date": hit.get("created_at", "")[:10],
                        "points": pts
                    })
    except Exception as e:
        pass
    return results

def scan_reddit(time_range="1d", min_faves=0, custom_query=""):
    """渠道 3: 扫描 Reddit (支持时间与爆款筛选)"""
    time_filter = f"when:{time_range}" if time_range else "when:1d"
    sub_q = custom_query if custom_query else '("launched" OR "built this" OR "showcase" OR "upvotes")'
    query = f'site:reddit.com/r/SideProject {sub_q} {time_filter}'
    raw_items = fetch_rss_feed(query)
    results = []
    for item in raw_items:
        title = item["title"].replace(" - Reddit", "")
        domain_matches = re.findall(r'\b[a-zA-Z0-9-]+\.(?:com|io|ai|co|app|dev|sh|tools)\b', item["title"])
        target_domain = None
        for dm in domain_matches:
            if dm.lower() not in GREYLIST:
                target_domain = dm.lower()
                break

        if target_domain:
            results.append({
                "channel": "Reddit (SideProject)",
                "badge_color": "bg-red-500",
                "title": title,
                "domain": target_domain,
                "url": f"https://{target_domain}",
                "source_url": item["link"],
                "pub_date": item["pubDate"]
            })
    return results

def scan_producthunt(time_range="1d", min_faves=0, custom_query=""):
    """渠道 4: 扫描 Product Hunt"""
    time_filter = f"when:{time_range}" if time_range else "when:1d"
    sub_q = custom_query if custom_query else "posts"
    query = f'site:producthunt.com/{sub_q} {time_filter}'
    raw_items = fetch_rss_feed(query)
    results = []
    for item in raw_items:
        title = item["title"].replace(" - Product Hunt", "")
        parts = title.split(" - ")
        prod_name = parts[0].strip() if parts else title
        results.append({
            "channel": "Product Hunt",
            "badge_color": "bg-amber-600",
            "title": title,
            "domain": prod_name.lower().replace(" ", "") + ".com",
            "url": item["link"],
            "source_url": item["link"],
            "pub_date": item["pubDate"]
        })
    return results

class RadarRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 增加 CORS 头与缓存控制
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/domain-age":
            params = urllib.parse.parse_qs(parsed.query)
            domain = params.get("domain", [""])[0]
            age_days, age_tag = fetch_domain_age(domain)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"domain": domain, "age_days": age_days, "age_tag": age_tag}, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/scan":
            params = urllib.parse.parse_qs(parsed.query)
            channels = params.get("channels", ["twitter,hn,reddit,producthunt"])[0].split(",")
            max_age = int(params.get("max_age", [999999])[0])
            time_range = params.get("time_range", ["1d"])[0]
            min_faves = int(params.get("min_faves", [0])[0])
            custom_query = params.get("query", [""])[0]

            all_items = []
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {}
                if "twitter" in channels:
                    futures["twitter"] = executor.submit(scan_twitter, time_range, min_faves, custom_query)
                if "hn" in channels:
                    futures["hn"] = executor.submit(scan_hackernews, time_range, min_faves, custom_query)
                if "reddit" in channels:
                    futures["reddit"] = executor.submit(scan_reddit, time_range, min_faves, custom_query)
                if "producthunt" in channels:
                    futures["producthunt"] = executor.submit(scan_producthunt, time_range, min_faves, custom_query)

                for k, fut in futures.items():
                    try:
                        all_items.extend(fut.result())
                    except Exception as e:
                        print(f"Channel {k} error:", e)

            # 去重（按 domain）
            unique_items = []
            seen_domains = set()
            for it in all_items:
                d = it.get("domain")
                if d and d not in seen_domains:
                    seen_domains.add(d)
                    unique_items.append(it)

            # 极速返回：不阻塞查询域名年龄，直接返回抓取到的新鲜项目
            final_items = []
            for it in unique_items[:30]:
                d = it["domain"]
                # 如果命中本地缓存或 PaaS，直接带上结果
                if d in DOMAIN_CACHE:
                    it["age_days"], it["age_tag"] = DOMAIN_CACHE[d]
                else:
                    it["age_days"] = None
                    it["age_tag"] = "⏳ 检测中..."
                final_items.append(it)

            # 输出 JSON
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"count": len(final_items), "items": final_items}, ensure_ascii=False).encode("utf-8"))
            return

        # 默认静态页面
        if parsed.path == "/" or parsed.path == "":
            self.path = "/index.html"
        return super().do_GET()

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"==================================================")
    print(f" 🚀 全渠道趋势雷达 (Multi-Channel Trend Radar)")
    print(f" 📡 监控渠道: Twitter/X | Show HN | Reddit | ProductHunt")
    print(f" 💡 特色: 100% 零 API Key 依赖，完全免费！")
    print(f" 🌐 本地仪表盘: http://{HOST}:{PORT}")
    print(f"==================================================")
    with ThreadingHTTPServer((HOST, PORT), RadarRequestHandler) as httpd:
        httpd.serve_forever()
