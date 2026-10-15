import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Условные данные: относительные расхождения параллельных определений, %
sigma_r = 4.0
cl, pp, pd = 1.128 * sigma_r, 2.834 * sigma_r, 3.686 * sigma_r

rng = np.random.default_rng(7)
x1 = rng.normal(0, sigma_r, 25)
x2 = rng.normal(0, sigma_r, 25)
r = np.abs(x1 - x2)
r = np.clip(r, 0.3, pp * 0.97)
r[17] = 12.1  # одна точка между ПП и ПД — для иллюстрации

n = np.arange(1, len(r) + 1)
fig, ax = plt.subplots(figsize=(8, 3.6), dpi=200)
ax.plot(n, r, color="#2f5d8a", lw=1.4, marker="o", ms=4, zorder=3)
ax.axhline(cl, color="#555555", lw=1, label=f"Средняя линия {cl:.1f} %")
ax.axhline(pp, color="#d08a1a", lw=1, ls="--", label=f"Предел предупреждения {pp:.1f} %")
ax.axhline(pd, color="#b03030", lw=1.2, label=f"Предел действия {pd:.1f} %")
ax.scatter([18], [r[17]], s=60, facecolors="none", edgecolors="#d08a1a", lw=1.5, zorder=4)

ax.set_xlabel("Номер контрольной процедуры")
ax.set_ylabel("rк, % от X̄")
ax.set_title("Контрольная карта повторяемости: аммоний-ион (условные данные)", fontsize=10)
ax.set_xlim(0.5, len(r) + 0.5)
ax.set_ylim(0, pd * 1.15)
ax.set_xticks(n[::2])
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.grid(axis="y", color="#e5e5e5", lw=0.6)
ax.legend(fontsize=7.5, loc="upper left", frameon=False, ncol=3)
fig.tight_layout()
fig.savefig("control_chart.png")
print(np.round(r, 1))
