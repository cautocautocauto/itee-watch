"""Monitora pagine ITEE e notifica su Telegram le modifiche.
Confronta solo le sezioni utili (testo + link), ignorando slider,
contatore visite e token CSRF che cambiano a ogni caricamento.

Uso:  python watch.py            -> un solo controllo
      python watch.py --loop     -> controlla ogni INTERVAL secondi per MAX_MINUTES
"""
import difflib, html, os, pathlib, subprocess, sys, time
import requests
from bs4 import BeautifulSoup

TARGETS = [
    {   # contenuto della pagina Ammissione
        "name": "ammissione",
        "label": "Pagina Ammissione XLII ciclo",
        "url": "https://itee.dieti.unina.it/index.php/it/ammissione/ammissione",
        "selector": '[itemprop="articleBody"]',
    },
    {   # riquadro News nella colonna destra della home
        "name": "news",
        "label": "News home ITEE",
        "url": "https://itee.dieti.unina.it/index.php/it/",
        "selector": "#sp-right .news-cycle",
    },
]
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
INTERVAL = int(os.getenv("INTERVAL", "60"))
MAX_MINUTES = float(os.getenv("MAX_MINUTES", "0"))  # 0 = infinito
GIT_PUSH = os.getenv("GIT_PUSH") == "1"
STATE_DIR = pathlib.Path(os.getenv("STATE_DIR", "state"))
STATE_DIR.mkdir(exist_ok=True)
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 itee-watch"


def send(text: str) -> None:
    session.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text[:4000], "parse_mode": "HTML",
              "disable_web_page_preview": "true"},
        timeout=30,
    ).raise_for_status()


def extract(content: bytes, selector: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    node = soup.select_one(selector)
    if node is None:
        raise RuntimeError(f"sezione '{selector}' non trovata")
    for s in node.find_all("script"):
        s.decompose()
    lines = [" ".join(t.split()) for t in node.get_text("\n").splitlines()]
    lines = [l for l in lines if l]
    links = sorted({a["href"] for a in node.find_all("a", href=True)
                    if not a["href"].startswith("mailto:")})
    return "\n".join(lines + ["--- LINK ---"] + links)


def git_save(msg: str) -> None:
    if not GIT_PUSH:
        return
    subprocess.run(["git", "add", str(STATE_DIR)], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        subprocess.run(["git", "commit", "-qm", msg], check=False)
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
        subprocess.run(["git", "push", "-q"], check=False)


def check(t: dict) -> None:
    state = STATE_DIR / f"{t['name']}.txt"
    try:
        r = session.get(t["url"], timeout=30)
        r.raise_for_status()
        new = extract(r.content, t["selector"])
    except Exception as e:  # sito giù o lento: riprova al giro dopo
        print(f"[{t['name']}] errore: {e}", file=sys.stderr)
        return

    if not state.exists():
        state.write_text(new, encoding="utf-8")
        send(f"✅ Monitoraggio avviato: {t['label']}\n{t['url']}")
        git_save(f"init {t['name']}")
        return

    old = state.read_text(encoding="utf-8")
    if old == new:
        return
    diff = [l for l in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    body = "\n".join(html.escape(l) for l in diff[:40]) or "(modifica non testuale)"
    send(f"🔔 <b>{t['label']} modificata!</b>\n{t['url']}\n\n<pre>{body}</pre>")
    state.write_text(new, encoding="utf-8")
    git_save(f"change {t['name']}")


def main() -> None:
    loop = "--loop" in sys.argv
    deadline = time.time() + MAX_MINUTES * 60 if MAX_MINUTES else float("inf")
    while True:
        start = time.time()
        for t in TARGETS:
            check(t)
        if not loop or time.time() + INTERVAL > deadline:
            break
        time.sleep(max(0, INTERVAL - (time.time() - start)))


if __name__ == "__main__":
    main()
