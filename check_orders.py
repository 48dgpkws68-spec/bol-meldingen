"""Checkt nieuwe bol-bestellingen en stuurt een pushmelding via ntfy."""
import base64, json, os, pathlib, urllib.request

CLIENT_ID = os.environ["BOL_CLIENT_ID"]
CLIENT_SECRET = os.environ["BOL_CLIENT_SECRET"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
STATE = pathlib.Path(__file__).with_name("seen.json")
BACKFILL = pathlib.Path(__file__).with_name("backfill.txt")  # order-ids die alsnog gemeld moeten worden (bijv. van voor de eerste run)
ACCEPT = "application/vnd.retailer.v10+json"


def request(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def token():
    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    return request("https://login.bol.com/token?grant_type=client_credentials", "POST",
                   {"Authorization": f"Basic {auth}", "Accept": "application/json"})["access_token"]


def notify(title, body):
    urllib.request.urlopen(urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(), method="POST",
        headers={"Title": title.encode("ascii", "ignore").decode(), "Tags": "moneybag", "Priority": "high"}), timeout=30)


def meld(oid, headers, eerder=False):
    detail = request(f"https://api.bol.com/retailer/orders/{oid}", headers=headers)
    lines, total = [], 0.0
    for item in detail.get("orderItems", []):
        qty = item.get("quantity", 1)
        name = item.get("product", {}).get("title") or item.get("offer", {}).get("reference") or "Product"
        price = float(item.get("unitPrice", 0)) * qty
        total += price
        lines.append(f"{qty}x {name} · €{price:.2f}".replace(".", ","))
    datum = (detail.get("orderPlacedDateTime") or "")[:10]
    extra = f"\nBesteld op {datum}" if datum else ""
    notify(f"{'Eerder verkocht' if eerder else 'Verkocht'} op bol: EUR {total:.2f}", "\n".join(lines) + extra + f"\nOrder {oid}")


def main():
    headers = {"Authorization": f"Bearer {token()}", "Accept": ACCEPT}
    if BACKFILL.exists():
        for oid in BACKFILL.read_text().split():
            meld(oid, headers, eerder=True)
        BACKFILL.write_text("")
    orders = []
    for method in ("FBR", "FBB"):
        data = request(f"https://api.bol.com/retailer/orders?status=ALL&fulfilment-method={method}", headers=headers)
        orders += data.get("orders", [])

    first_run = not STATE.exists()
    seen = set(json.loads(STATE.read_text())) if not first_run else set()

    for o in orders:
        oid = o["orderId"]
        if oid in seen:
            continue
        seen.add(oid)
        if first_run:  # bestaande orders niet melden bij de eerste keer
            continue
        meld(oid, headers)

    STATE.write_text(json.dumps(sorted(seen)))


if __name__ == "__main__":
    main()
