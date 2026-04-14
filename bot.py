import os, sqlite3, hashlib, asyncio, logging, feedparser
from datetime import datetime
from io import BytesIO
from google import genai
from google.genai import types
from telegram import Bot
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

GEMINI_API_KEY      = "AIzaSyBudCaTud4qvnoauJ31lRDbAOpXkSSVn4c"
FOOTBALL_API_KEY    = "1402e1c873f3401f85319fe58117c03f"
TELEGRAM_BOT_TOKEN  = "8576826909:AAFTrMH0z9ZxLsTQtjE_S0kyY41xS38C910"
TELEGRAM_CHANNEL_ID = "-1003940397119"
TEXT_MODEL          = "gemini-3-flash-preview"
IMAGE_MODEL         = "gemini-3.1-flash-image-preview"
MAX_NEWS_PER_RUN    = 2

RSS_FEEDS = [
    {"url":"https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml","source":"BBC Sport","competition":"英超"},
    {"url":"https://www.skysports.com/rss/12040","source":"Sky Sports","competition":"英超"},
    {"url":"https://feeds.bbci.co.uk/sport/football/european/rss.xml","source":"BBC Sport","competition":"欧冠"},
    {"url":"https://www.goal.com/feeds/en/news","source":"Goal.com","competition":"综合"},
]

KEYWORDS = ["premier league","champions league","world cup","arsenal","chelsea","liverpool",
            "man city","man united","tottenham","real madrid","barcelona","transfer","goal","injury"]

def init_db():
    conn = sqlite3.connect("news_sent.db")
    conn.execute("CREATE TABLE IF NOT EXISTS sent_news (id TEXT PRIMARY KEY, title TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit(); conn.close()

def is_sent(nid):
    conn = sqlite3.connect("news_sent.db")
    r = conn.execute("SELECT 1 FROM sent_news WHERE id=?",(nid,)).fetchone()
    conn.close(); return r is not None

def mark_sent(nid, title):
    conn = sqlite3.connect("news_sent.db")
    conn.execute("INSERT OR IGNORE INTO sent_news(id,title) VALUES(?,?)",(nid,title))
    conn.commit(); conn.close()

def news_id(title): return hashlib.md5(title.lower().strip().encode()).hexdigest()

def fetch_news():
    all_news, seen = [], set()
    for f in RSS_FEEDS:
        try:
            feed = feedparser.parse(f["url"])
            for e in feed.entries[:10]:
                title   = e.get("title","")
                summary = e.get("summary", e.get("description",""))[:500]
                link    = e.get("link","")
                if not any(k in (title+summary).lower() for k in KEYWORDS): continue
                nid = news_id(title)
                if is_sent(nid) or nid in seen: continue
                seen.add(nid)
                all_news.append({"id":nid,"title":title,"summary":summary,"link":link,"source":f["source"],"competition":f["competition"]})
        except Exception as e:
            logging.error(f"RSS error {f['source']}: {e}")
    return all_news[:MAX_NEWS_PER_RUN]

def gen_caption(client, news):
    r = client.models.generate_content(model=TEXT_MODEL, contents=f"""
你是马来西亚足球新闻编辑，写给本地华人球迷看。
标题：{news['title']}
摘要：{news['summary']}
赛事：{news['competition']}

用中文写一篇简短新闻帖子：
- 第一行：吸引人的中文标题（不超过20字）
- 正文：2-3句口语化中文
- 2-3个相关emoji
- hashtag：#英超 #欧冠 #足球 等
""")
    return r.text.strip()

def gen_image(client, headline):
    try:
        r = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=f'Create a dramatic football news graphic. Dark background, green pitch elements, bold white text showing: "{headline[:60]}". Modern sports broadcast style, cinematic lighting.',
            config=types.GenerateContentConfig(response_modalities=["IMAGE","TEXT"])
        )
        for part in r.candidates[0].content.parts:
            if part.inline_data: return part.inline_data.data
    except Exception as e:
        logging.error(f"Image error: {e}")
    return None

async def send(bot, caption, img, link, source):
    full = f"{caption}\n\n🔗 [原文]({link}) | 📰 {source}"[:1000]
    try:
        if img:
            f = BytesIO(img); f.name="news.png"
            await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=f, caption=full, parse_mode=ParseMode.MARKDOWN)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=full, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def run():
    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] 检查新闻...")
    gc = genai.Client(api_key=GEMINI_API_KEY)
    tb = Bot(token=TELEGRAM_BOT_TOKEN)
    news_list = fetch_news()
    if not news_list: logging.info("没有新新闻"); return
    logging.info(f"找到 {len(news_list)} 条")
    for n in news_list:
        try:
            caption = gen_caption(gc, n)
            img     = gen_image(gc, n["title"])
            await send(tb, caption, img, n["link"], n["source"])
            mark_sent(n["id"], n["title"])
            logging.info(f"✅ {n['title'][:50]}")
            await asyncio.sleep(3)
        except Exception as e:
            logging.error(f"Error: {e}")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    init_db()
    logging.info("⚽ Football News Bot 启动！每10分钟一次")
    await run()
    s = AsyncIOScheduler()
    s.add_job(run, "interval", minutes=10)
    s.start()
    try:
        while True: await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        s.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
