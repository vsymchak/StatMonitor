import io
from datetime import timezone

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    matplotlib = None
    plt = None
    mdates = None

from statmonitor.config import KYIV_TZ

def build_chart(cur, conn, ev_id, bm, out_n, pt, match, title, pick_lbl, sc):
    try:
        if plt is None:
            return None
        if not (sc.get("outcome") and sc.get("price") and sc.get("time")):
            return None
        q = f"SELECT {sc['time']}, {sc['price']} FROM odds_history WHERE {sc['event_id']}=%s AND {sc['bookmaker']}=%s AND {sc['outcome']}=%s"
        args = [ev_id, bm, out_n]
        if sc.get("point"):
            q += f" AND {sc['point']}=%s" if pt is not None else f" AND {sc['point']} IS NULL"
            if pt is not None:
                args.append(pt)
        cur.execute(q + f" ORDER BY {sc['time']} ASC;", tuple(args))
        rows = cur.fetchall()
        if len(rows) < 2:
            return None
        times = [(r[0].replace(tzinfo=timezone.utc) if r[0].tzinfo is None else r[0]).astimezone(KYIV_TZ) for r in rows]
        prices = [float(r[1]) for r in rows]

        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=130)
        ax.plot(times, prices, marker="o", linewidth=2.2, markersize=5, color="#c0392b")
        for t, p in zip(times, prices):
            ax.annotate(f"{p:.2f}", (t, p), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, fontweight="bold")
        ax.set_title(f"{match} ({title})\nСтавка: {pick_lbl} | БК: {bm}", fontsize=10, fontweight="bold", pad=12)
        ax.grid(True, linestyle="--", alpha=0.45)
        margin = max(0.05, (max(prices) - min(prices)) * 0.25)
        ax.set_ylim(min(prices) - margin, max(prices) + margin)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=KYIV_TZ))
        fig.autofmt_xdate(rotation=25)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Chart build err: {e}")
        return None
