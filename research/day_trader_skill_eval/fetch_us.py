"""Fetch Yahoo charts for a liquid US universe: 60d of 5m bars and 10y of daily bars.
Saved raw (the skill's own parser reads them). Polite: 0.4 s between requests."""
import json, os, sys, time, urllib.request, gzip

OUT = os.path.join(os.path.dirname(__file__), "us")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
# ~150 of the most traded US names (large caps across sectors + popular day-trading names)
SYMS = """AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD NFLX ORCL CRM ADBE INTC QCOM MU TXN AMAT LRCX KLAC
MRVL ARM SMCI PLTR SNOW UBER ABNB SHOP COIN MSTR HOOD SOFI RIVN LCID NIO PLUG F GM BA CAT DE GE HON LMT RTX
JPM BAC WFC C GS MS SCHW AXP V MA PYPL XOM CVX COP OXY SLB HAL DVN MPC PSX UNH LLY JNJ PFE MRK ABBV BMY AMGN
GILD MRNA CVS WMT COST TGT HD LOW NKE SBUX MCD KO PEP PG DIS CMCSA T VZ TMUS CCL RCL NCLH DAL UAL AAL LUV
MARA RIOT CLSK AFRM UPST DKNG RBLX SNAP PINS ROKU ZM DOCU NET CRWD PANW ZS DDOG MDB OKTA TEAM WDAY NOW INTU
IBM CSCO DELL HPQ WBD PARA BABA JD PDD BIDU TSM ASML SONY TM GME AMC CHWY ETSY EBAY W ENPH FSLR NEE DUK SO
X CLF AA FCX NEM GOLD VALE BHP KHC MDLZ""".split()


def get(url):
    for host in ("query2", "query1"):
        req = urllib.request.Request(url.replace("HOST", host), headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2)
    raise err


def main():
    os.makedirs(os.path.join(OUT, "5m"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "1d"), exist_ok=True)
    bad = []
    for s in SYMS:
        for kind, q in (("5m", "range=60d&interval=5m"), ("1d", "range=10y&interval=1d")):
            p = os.path.join(OUT, kind, s + ".json.gz")
            if os.path.exists(p):
                continue
            try:
                t = get("https://HOST.finance.yahoo.com/v8/finance/chart/%s?%s&includePrePost=false" % (s, q))
                with gzip.open(p, "wt") as f:
                    f.write(t)
            except Exception as e:  # noqa: BLE001
                bad.append((s, kind, str(e)[:80]))
            time.sleep(0.4)
    print("done", len(SYMS), "symbols; failed:", bad)


if __name__ == "__main__":
    main()
