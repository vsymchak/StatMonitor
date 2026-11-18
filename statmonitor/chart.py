import io
from datetime import timezone, timedelta

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as ticker
except ImportError:
    matplotlib = None
    plt = None
    mdates = None
    ticker = None

from statmonitor.config import KYIV_TZ

def build_weekly_equity_chart(history_points, start_bank=10000.0, end_bank=None, title="Динаміка капіталу (Paper Trading)"):
    """
    Будує графік балансу/капіталу для щотижневого фінансового дайджесту у Telegram.
    history_points: список кортежів (datetime_obj, balance_float), відсортований за часом.
    Повертає io.BytesIO з PNG-зображенням або None.
    """
    try:
        if plt is None:
            return None
        if not history_points:
            return None

        # Підготовка точок
        parsed_pts = []
        for dt, bal in history_points:
            if not hasattr(dt, "tzinfo") or not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed_pts.append((dt.astimezone(KYIV_TZ), float(bal)))

        parsed_pts.sort(key=lambda x: x[0])

        # Якщо лише 1 точка, додаємо стартову за 12 годин до неї
        if len(parsed_pts) == 1:
            first_dt, first_bal = parsed_pts[0]
            parsed_pts.insert(0, (first_dt - timedelta(hours=12), float(start_bank)))

        times = [p[0] for p in parsed_pts]
        balances = [p[1] for p in parsed_pts]

        cur_balance = balances[-1] if end_bank is None else float(end_bank)
        profit = cur_balance - float(start_bank)
        growth_pct = (profit / float(start_bank) * 100.0) if start_bank > 0 else 0.0

        # Створення фігури в елегантному фінансовому стилі
        fig, ax = plt.subplots(figsize=(8.0, 4.2), dpi=140)
        fig.patch.set_facecolor("#FFFFFF")
        ax.set_facecolor("#FAFAFC")

        # Стартова горизонтальна лінія
        ax.axhline(
            start_bank,
            color="#94A3B8",
            linestyle="--",
            linewidth=1.4,
            alpha=0.85,
            label=f"Старт ({start_bank:,.0f} ₴)",
        )

        # Крива балансу
        line_color = "#2563EB"  # Фірмовий синій
        ax.plot(
            times,
            balances,
            marker="o",
            linewidth=2.6,
            markersize=5.5,
            color=line_color,
            markerfacecolor=line_color,
            markeredgecolor="#FFFFFF",
            markeredgewidth=1.6,
            label=f"Баланс ({cur_balance:,.0f} ₴)",
            zorder=4,
        )

        # Напівпрозора заливка до стартового рівня
        ax.fill_between(
            times,
            balances,
            start_bank,
            color=line_color,
            alpha=0.10,
            zorder=2,
        )

        # Анотація крайніх точок
        first_t, first_b = times[0], balances[0]
        last_t, last_b = times[-1], balances[-1]
        
        ax.annotate(
            f"{first_b:,.0f} ₴",
            (first_t, first_b),
            textcoords="offset points",
            xytext=(0, -18 if first_b >= start_bank else 10),
            ha="center",
            fontsize=8.5,
            fontweight="semibold",
            color="#475569",
        )

        sign = "+" if profit >= 0 else ""
        badge_txt = f"{last_b:,.0f} ₴ ({sign}{growth_pct:.1f}%)"
        ax.annotate(
            badge_txt,
            (last_t, last_b),
            textcoords="offset points",
            xytext=(0, 10 if last_b >= start_bank else -18),
            ha="center",
            fontsize=9.5,
            fontweight="bold",
            color="#1E293B",
            bbox=dict(boxstyle="round,pad=0.28", fc="#EFF6FF", ec="#BFDBFE", lw=1),
            zorder=5,
        )

        # Заголовок та підзаголовок
        sub_sign = "+" if profit >= 0 else ""
        subtitle = f"Прибуток: {sub_sign}{profit:,.2f} ₴  •  ROI: {sub_sign}{growth_pct:.1f}%"
        ax.set_title(f"{title}\n{subtitle}", fontsize=11, fontweight="bold", color="#0F172A", pad=12)

        # Сітка та оформлення осей
        ax.grid(True, linestyle=":", alpha=0.6, color="#CBD5E1")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#E2E8F0")
        ax.spines["bottom"].set_color("#E2E8F0")

        # Форматування X осі
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m", tz=KYIV_TZ))
        fig.autofmt_xdate(rotation=0, ha="center")
        ax.tick_params(axis="both", which="major", labelsize=8.5, colors="#64748B")

        # Межі Y з запасом
        min_y = min(balances + [start_bank])
        max_y = max(balances + [start_bank])
        pad_y = max((max_y - min_y) * 0.22, 250.0)
        ax.set_ylim(min_y - pad_y, max_y + pad_y)

        # Форматування чисел на осі Y (наприклад: 10,500 ₴)
        if ticker:
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{int(x):,} ₴".replace(",", " ")))

        ax.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#E2E8F0", fontsize=8.5)

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=140)
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Weekly chart build err: {e}")
        return None

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
