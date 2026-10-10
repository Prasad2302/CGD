"""Core LP for the CGD Gas Allocation & Network Optimization DSS.

Formulation (per month t):
  min  sum_arcs (c_a + g*[arc leaves city gate]) x_a + sum_n p_n y_n + M * sum_n s_n
  s.t. sum_{a out of G} x_a <= A_t                        (source availability)
       inflow(n) - outflow(n) + y_n = D_n,t   for demand nodes (node balance with transshipment)
       sum_{a in corridor k} x_a <= u_k                   (corridor capacity)
       y_n <= (1 - alpha_n) * D_n,t + s_n                 (elastic priority-tier service floor)
       x, y, s >= 0
Solved with SciPy HiGHS, which also returns the dual values (shadow prices).
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from scipy.optimize import linprog

NODES = ["A", "B", "P1", "P2", "P3", "P4", "I1", "I2"]
TIER = {"A": "CNG", "B": "CNG", "P1": "PNG", "P2": "PNG", "P3": "PNG", "P4": "PNG", "I1": "IND", "I2": "IND"}
# (from, to, corridor)
ARCS = [("G", "A", 1), ("A", "B", 2), ("G", "P1", 3), ("G", "P2", 3),
        ("P1", "P3", 4), ("P1", "P4", 4), ("P2", "P3", 4), ("P2", "P4", 4),
        ("G", "I1", 5), ("G", "I2", 5)]
CORRIDOR_COST = {1: 2.0, 2: 1.5, 3: 1.8, 4: 1.2, 5: 2.5}          # Rs/SCM
CORRIDOR_CAP = {1: 10000, 2: 8000, 3: 12000, 4: 9000, 5: 6000}    # SCM/month
CORRIDOR_NAME = {1: "C1 G->A", 2: "C2 A->B", 3: "C3 G->P1,P2", 4: "C4 P1,P2->P3,P4", 5: "C5 G->I1,I2"}
SUPPLY = [11000, 11500, 11200, 11800, 12000, 12500, 12300, 11900, 11600, 11500, 11000, 10800]
D_M1 = dict(zip(NODES, [2500, 2000, 1800, 1600, 1700, 1400, 1500, 1000]))
D_M12 = dict(zip(NODES, [2700, 2200, 2000, 1800, 1900, 1500, 1700, 1100]))


def default_demand() -> pd.DataFrame:
    """Canvas gives only Month 1 and Month 12: months 2-11 are LINEAR INTERPOLATION (assumption)."""
    rows = [{n: D_M1[n] + (D_M12[n] - D_M1[n]) * (t - 1) / 11 for n in NODES} for t in range(1, 13)]
    return pd.DataFrame(rows, index=range(1, 13))


@dataclass
class Params:
    supply_pct: float = 0.0
    demand_pct: float = 0.0
    gas_cost: float = 32.0          # Rs/SCM (MGL reports ~Rs 32-33.65/SCM in FY26)
    pen_png: float = 60.0           # Tier 1 shortage penalty, Rs/SCM (must exceed delivered cost)
    pen_cng: float = 50.0           # Tier 2
    pen_ind: float = 40.0           # Tier 3
    alpha_png: float = 0.95
    alpha_cng: float = 0.90
    alpha_ind: float = 0.80
    big_m: float = 500.0            # penalty on violating a service floor, Rs/SCM
    cap_scale: dict = field(default_factory=lambda: {k: 1.0 for k in range(1, 6)})
    supply: list = field(default_factory=lambda: list(SUPPLY))
    demand: pd.DataFrame = field(default_factory=default_demand)

    def pen(self, n):
        return {"PNG": self.pen_png, "CNG": self.pen_cng, "IND": self.pen_ind}[TIER[n]]

    def alpha(self, n):
        return {"PNG": self.alpha_png, "CNG": self.alpha_cng, "IND": self.alpha_ind}[TIER[n]]

    def cap(self, k):
        return CORRIDOR_CAP[k] * self.cap_scale[k]

    def copy_with(self, **kw):
        d = dict(self.__dict__)
        d["cap_scale"] = dict(self.cap_scale)
        d.update(kw)
        return Params(**d)


def solve_month(t: int, p: Params) -> dict:
    na, nn = len(ARCS), len(NODES)
    nv = na + 2 * nn                                   # x (arcs), y (shortage), s (floor violation)
    D = p.demand.loc[t].values * (1 + p.demand_pct / 100)
    A_t = p.supply[t - 1] * (1 + p.supply_pct / 100)
    c = np.zeros(nv)
    for i, (a, b, k) in enumerate(ARCS):
        c[i] = CORRIDOR_COST[k] + (p.gas_cost if a == "G" else 0.0)
    for j, n in enumerate(NODES):
        c[na + j] = p.pen(n)
        c[na + nn + j] = p.big_m
    A_eq = np.zeros((nn, nv)); b_eq = np.zeros(nn)
    for j, n in enumerate(NODES):
        for i, (a, b, k) in enumerate(ARCS):
            if b == n: A_eq[j, i] += 1
            if a == n: A_eq[j, i] -= 1
        A_eq[j, na + j] = 1
        b_eq[j] = D[j]
    A_ub, b_ub, names = [], [], []
    r = np.zeros(nv)
    for i, (a, b, k) in enumerate(ARCS):
        if a == "G": r[i] = 1
    A_ub.append(r); b_ub.append(A_t); names.append("source")
    for k in range(1, 6):
        r = np.zeros(nv)
        for i, (a, b, kk) in enumerate(ARCS):
            if kk == k: r[i] = 1
        A_ub.append(r); b_ub.append(p.cap(k)); names.append(f"c{k}")
    for j, n in enumerate(NODES):
        r = np.zeros(nv); r[na + j] = 1; r[na + nn + j] = -1
        A_ub.append(r); b_ub.append((1 - p.alpha(n)) * D[j]); names.append(f"floor_{n}")
    res = linprog(c, A_ub=np.array(A_ub), b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=(0, None), method="highs")
    if res.status != 0:
        raise RuntimeError(f"LP failed in month {t}: {res.message}")
    x = res.x
    flows = {k: sum(x[i] for i, (a, b, kk) in enumerate(ARCS) if kk == k) for k in range(1, 6)}
    duals = dict(zip(names, res.ineqlin.marginals))
    gas = sum(x[i] * p.gas_cost for i, (a, b, k) in enumerate(ARCS) if a == "G")
    trans = sum(x[i] * CORRIDOR_COST[k] for i, (a, b, k) in enumerate(ARCS))
    y = x[na:na + nn]
    return dict(month=t, supply=A_t, demand=float(D.sum()), cost=res.fun, gas=gas, transport=trans,
                penalty=float(sum(y[j] * p.pen(n) for j, n in enumerate(NODES))),
                shortage=float(y.sum()), violation=float(x[na + nn:].sum()),
                flows=flows, duals=duals, y=dict(zip(NODES, y)), delivered=dict(zip(NODES, D - y)),
                arc_flows=x[:na])


def solve_all(p: Params):
    """Returns (monthly DataFrame, list of raw month results)."""
    raw = [solve_month(t, p) for t in range(1, 13)]
    df = pd.DataFrame([{
        "Month": r["month"], "Supply": r["supply"], "Demand": r["demand"], "Cost (Rs)": r["cost"],
        "Gas cost": r["gas"], "Transport": r["transport"], "Penalty": r["penalty"],
        "Shortage": r["shortage"], "Floor violation": r["violation"],
        **{f"C{k} flow": r["flows"][k] for k in range(1, 6)},
        "Source shadow (Rs/SCM)": r["duals"]["source"]} for r in raw])
    return df, raw


def corridor_table(p: Params, raw) -> pd.DataFrame:
    rows = []
    for k in range(1, 6):
        peak = max(r["flows"][k] for r in raw)
        rows.append({"Corridor": CORRIDOR_NAME[k], "Capacity": p.cap(k), "Peak flow": peak,
                     "Utilisation %": 100 * peak / p.cap(k),
                     "Avg shadow (Rs/SCM)": float(np.mean([r["duals"][f"c{k}"] for r in raw])),
                     "Binding": peak >= p.cap(k) * 0.995,
                     "Binds below % cap": 100 * peak / CORRIDOR_CAP[k]})
    return pd.DataFrame(rows)


def corridor_sweep(p: Params, scales=(1.0, 0.6, 0.4, 0.3, 0.2, 0.1)) -> pd.DataFrame:
    """Corridor-wise sensitivity: cut ONE corridor's capacity, keep the others as in p."""
    rows = []
    for k in range(1, 6):
        for s in scales:
            q = p.copy_with(); q.cap_scale[k] = p.cap_scale[k] * s
            df, raw = solve_all(q)
            rows.append({"Corridor": CORRIDOR_NAME[k], "k": k, "Capacity %": int(s * 100),
                         "Capacity": q.cap(k), "Total cost": df["Cost (Rs)"].sum(),
                         "Shortage": df["Shortage"].sum(), "Floor violation": df["Floor violation"].sum(),
                         "Avg shadow (Rs/SCM)": float(np.mean([r["duals"][f"c{k}"] for r in raw]))})
    out = pd.DataFrame(rows)
    base = out[out["Capacity %"] == 100].set_index("k")["Total cost"]
    out["Delta vs full"] = out.apply(lambda r: r["Total cost"] - base[r["k"]], axis=1)
    return out


def one_way(p: Params, field_name: str, values):
    rows = []
    for v in values:
        q = p.copy_with(**{field_name: v})
        df, _ = solve_all(q)
        rows.append({field_name: v, "Total cost": df["Cost (Rs)"].sum(),
                     "Shortage": df["Shortage"].sum(), "Floor violation": df["Floor violation"].sum()})
    return pd.DataFrame(rows)


def escalation(p: Params, pcts=(0, 2, 5, 7.5, 10)) -> pd.DataFrame:
    base = solve_all(p)[0]["Cost (Rs)"].sum()
    rows = []
    for e in pcts:
        q = p.copy_with(gas_cost=p.gas_cost * (1 + e / 100))
        tot = solve_all(q)[0]["Cost (Rs)"].sum()
        rows.append({"Escalation %": e, "Total cost": tot, "Delta": tot - base, "Delta %": 100 * (tot / base - 1)})
    return pd.DataFrame(rows)
