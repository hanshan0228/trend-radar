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

# 灰名单：忽略知名成熟平台、大厂官方域名、社交媒体等
GREYLIST = {
    "google.com", "github.com", "youtube.com", "twitter.com", "x.com",
    "reddit.com", "producthunt.com", "ycombinator.com", "medium.com",
    "linkedin.com", "apple.com", "amazon.com", "wikipedia.org", "t.co",
    "bit.ly", "instagram.com", "facebook.com", "tiktok.com", "discord.com",
    "discord.gg", "substack.com", "notion.site", "loom.com", "figma.com",
    "microsoft.com", "techcrunch.com", "theverge.com", "bloomberg.com",
    "forbes.com", "wired.com", "news.ycombinator.com", "imgur.com",
    # 超级大厂与公关官方号域名
    "openai.com", "anthropic.com", "claude.ai", "claude.com", "deepseek.com",
    "nvidia.com", "meta.com", "servicenow.com", "salesforce.com", "adobe.com",
    "netflix.com", "spotify.com", "huggingface.co", "adidas.com", "nike.com"
}

# 过滤大厂企业级通稿标题关键词（独立开发者雷达不看大厂官方通稿）
CORP_KEYWORDS = {
    "anthropic just", "openai just", "google just", "nvidia just", "microsoft just",
    "chatgpt just", "the white house", "servicenow just", "deepseek just", "google’s",
    "world heavyweight", "wwe", "senate", "republicans for", "democrats for"
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

    # 特殊社交平台标记：属于平台帖子，而非独立注册的新域名
    if domain.startswith("x.com"):
        res = (None, "🐦 X 动态(无独立域名)")
        DOMAIN_CACHE[domain] = res
        return res
    if domain.startswith("reddit.com"):
        res = (None, "🔴 Reddit 动态(无独立域名)")
        DOMAIN_CACHE[domain] = res
        return res

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
    """渠道 1: 扫描 X/Twitter (锁定独立开发/新工具，排除大厂公关营销号)"""
    time_filter = f"when:{time_range}" if time_range else "when:3d"

    if custom_query:
        query_core = f"({custom_query})"
    elif min_faves >= 300:
        query_core = '("built a tool" OR "built an app" OR "made a tool" OR "launched my app" OR "launched my tool" OR "my new tool" OR "my new app" OR "my side project")'
    else:
        query_core = '("built a tool" OR "built an app" OR "made a tool" OR "launched my tool" OR "launched my app" OR "my new tool" OR "my side project" OR "side project alert")'

    # 排除大厂公关噪音频道
    query = f'site:x.com {query_core} -openai -anthropic -google -nvidia -microsoft -whitehouse {time_filter}'
    raw_items = fetch_rss_feed(query)
    results = []
    for item in raw_items:
        title = item["title"].replace(" - Twitter", "").replace(" - X", "").strip()

        # 检查是否为大厂官方通稿
        lower_title = title.lower()
        if any(corp in lower_title for corp in CORP_KEYWORDS):
            continue

        # 1. 优先提取标题中的独立域名 (如 mytool.ai, catcollector.app)
        domain_matches = re.findall(r'\b[a-zA-Z0-9-]+\.(?:com|io|ai|co|app|dev|sh|org|tools|net|xyz|me)\b', title)
        target_domain = None
        target_url = item["link"]
        for dm in domain_matches:
            if dm.lower() not in GREYLIST:
                target_domain = dm.lower()
                target_url = f"https://{target_domain}"
                break

        # 2. 尝试从发布动词后提取产品名称 (如 Launching my new app, Who Goes -> whogoes.com)
        if not target_domain:
            m = re.search(r'(?:launching|launched|built|made|created|named|called)\s+(?:my\s+)?(?:new\s+)?(?:app|tool|saas|project|site|website)[,\s:]+([A-Z][a-zA-Z0-9_-]{2,20})', title, re.I)
            if m:
                pname = m.group(1).lower()
                if pname not in {"google", "claude", "chatgpt", "openai", "apple", "nvidia"}:
                    target_domain = f"{pname}.com"
                    target_url = item["link"]

        # 3. 尝试从 @提及 中提取独立作者 (排除大厂账号)
        if not target_domain:
            mentions = re.findall(r'@([a-zA-Z0-9_]{3,20})', title)
            for handle in mentions:
                hl = handle.lower()
                if hl not in {"openai", "anthropic", "google", "nvidia", "x", "twitter", "microsoft", "apple", "claude", "chatgpt"}:
                    target_domain = f"{hl}.com"
                    target_url = f"https://x.com/{handle}"
                    break

        # 4. 兜底为 x.com/post
        if not target_domain:
            target_domain = "x.com/post"
            target_url = item["link"]

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
    """渠道 3: 扫描 Reddit (直连 r/SideProject 官方 RSS 提炼独立项目)"""
    results = []
    # 策略 1: 优先直连 Reddit 官方高质量 RSS 源 (含正文与外部项目链接)
    try:
        url = 'https://www.reddit.com/r/SideProject/.rss'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            entries = root.findall('{http://www.w3.org/2005/Atom}entry')
            for e in entries:
                title = e.find('{http://www.w3.org/2005/Atom}title').text or ""
                link = e.find('{http://www.w3.org/2005/Atom}link').attrib.get('href') if e.find('{http://www.w3.org/2005/Atom}link') is not None else ""
                body = e.find('{http://www.w3.org/2005/Atom}content').text if e.find('{http://www.w3.org/2005/Atom}content') is not None else ""

                # 提取正文或标题中的外部独立域名
                domains = re.findall(r'https?://(?:www\.)?([a-zA-Z0-9-]+\.(?:com|io|ai|co|app|dev|sh|org|tools|net|xyz|me))', body + " " + title)
                target_domain = None
                for d in domains:
                    dl = d.lower()
                    if dl not in GREYLIST and "reddit" not in dl and "redd.it" not in dl:
                        target_domain = dl
                        break

                if not target_domain:
                    # 从标题推导产品名
                    m = re.search(r'(?:launched|built|introducing|created|called|named)\s+([A-Z][a-zA-Z0-9_-]{2,20})', title)
                    if m:
                        target_domain = f"{m.group(1).lower()}.com"

                if not target_domain:
                    target_domain = "reddit.com/r/SideProject"

                results.append({
                    "channel": "Reddit (SideProject)",
                    "badge_color": "bg-red-500",
                    "title": title.strip(),
                    "domain": target_domain,
                    "url": f"https://{target_domain}" if not target_domain.startswith("reddit.com") else link,
                    "source_url": link,
                    "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
                })
    except Exception as e:
        pass

    # 策略 2: 若直连失败则走 Google News 搜索兜底
    if not results:
        sub_q = custom_query if custom_query else '("launched" OR "built this" OR "showcase" OR "upvotes")'
        query = f'site:reddit.com/r/SideProject {sub_q}'
        raw_items = fetch_rss_feed(query)
        for item in raw_items:
            title = item["title"].replace(" - Reddit", "").strip()
            domain_matches = re.findall(r'\b[a-zA-Z0-9-]+\.(?:com|io|ai|co|app|dev|sh|tools|xyz|me)\b', title)
            target_domain = None
            for dm in domain_matches:
                if dm.lower() not in GREYLIST:
                    target_domain = dm.lower()
                    break
            if not target_domain:
                target_domain = "reddit.com/r/SideProject"
            results.append({
                "channel": "Reddit (SideProject)",
                "badge_color": "bg-red-500",
                "title": title,
                "domain": target_domain,
                "url": f"https://{target_domain}" if not target_domain.startswith("reddit.com") else item["link"],
                "source_url": item["link"],
                "pub_date": item["pubDate"]
            })
    return results

def scan_producthunt(time_range="1d", min_faves=0, custom_query=""):
    """渠道 4: 扫描 Product Hunt (官方实时 Atom Feed 直连 + Google News 兜底)"""
    results = []
    # 策略 1: 优先直连 Product Hunt 官方最新发布 Feed (当天 50 款首发产品)
    try:
        url = 'https://www.producthunt.com/feed'
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            root = ET.fromstring(resp.read())
            entries = root.findall('{http://www.w3.org/2005/Atom}entry')
            for e in entries:
                title = e.find('{http://www.w3.org/2005/Atom}title').text or ""
                link = e.find('{http://www.w3.org/2005/Atom}link').attrib.get('href') if e.find('{http://www.w3.org/2005/Atom}link') is not None else ""
                prod_name = title.split(" - ")[0].strip() if " - " in title else title.strip()
                clean_name = re.sub(r'[^a-zA-Z0-9]', '', prod_name).lower()
                target_domain = f"{clean_name}.com" if clean_name else "producthunt.com"

                # 排除大厂
                if any(corp in title.lower() for corp in CORP_KEYWORDS):
                    continue

                results.append({
                    "channel": "Product Hunt",
                    "badge_color": "bg-amber-600",
                    "title": title.strip(),
                    "domain": target_domain,
                    "url": link,
                    "source_url": link,
                    "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
                })
    except Exception as e:
        pass

    # 策略 2: 兜底
    if not results:
        time_filter = f"when:{time_range}" if time_range else "when:3d"
        sub_q = custom_query if custom_query else "posts"
        query = f'site:producthunt.com/{sub_q} {time_filter}'
        raw_items = fetch_rss_feed(query)
        for item in raw_items:
            title = item["title"].replace(" - Product Hunt", "").strip()
            parts = title.split(" - ")
            prod_name = parts[0].strip() if parts else title
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', prod_name).lower()
            results.append({
                "channel": "Product Hunt",
                "badge_color": "bg-amber-600",
                "title": title,
                "domain": f"{clean_name}.com" if clean_name else "producthunt.com",
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

            # 极速返回：若指定了域名年限，先过滤掉已确定不符合条件或非独立域名的项目
            final_items = []
            for it in unique_items:
                d = it["domain"]

                # 如果用户设置了严格年限 (如 <= 30天 或 <= 180天)
                if max_age <= 180:
                    # 社交平台自身帖子并非独立域名，直接剔除
                    if d.startswith("x.com") or d.startswith("reddit.com"):
                        continue

                # 如果命中本地缓存或 PaaS，直接带上结果
                if d in DOMAIN_CACHE:
                    age_days, age_tag = DOMAIN_CACHE[d]
                    it["age_days"] = age_days
                    it["age_tag"] = age_tag
                    # 如果已知天数且大于最大年限，排除
                    if max_age < 999999 and (age_days is None or age_days > max_age):
                        continue
                else:
                    it["age_days"] = None
                    it["age_tag"] = "⏳ 检测中..."

                final_items.append(it)
                if len(final_items) >= 30:
                    break

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
