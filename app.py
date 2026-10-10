"""CGD Planning DSS - Gas Allocation & Network Optimization (Streamlit)."""
import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import model as M

st.set_page_config(page_title="CGD Planning DSS", page_icon="🔥", layout="wide")
_orig_pc, _cnt = st.plotly_chart, [0]


def _pc(fig, **kw):  # unique keys so repeated charts never clash
    _cnt[0] += 1
    kw.setdefault("use_container_width", True)
    return _orig_pc(fig, key=f"pc{_cnt[0]}", **kw)


st.plotly_chart = _pc
TEAL, ORANGE, RED, GREEN = "#0b6e8a", "#c2410c", "#b42318", "#157347"
MONTHS = list(range(1, 13))

# ----------------------------------------------------------------- sidebar
st.sidebar.title("LP controls")
supply_pct = st.sidebar.slider("Supply change (%)", -30, 20, 0)
demand_pct = st.sidebar.slider("Demand change (%)", -10, 40, 0)
gas_cost = st.sidebar.slider("Gas purchase cost (Rs/SCM)", 28.0, 40.0, 32.0, 0.5)
st.sidebar.subheader("Shortage penalties (Rs/SCM)")
pen_png = st.sidebar.slider("Tier 1 PNG households", 20, 100, 60)
pen_cng = st.sidebar.slider("Tier 2 CNG stations", 20, 100, 50)
pen_ind = st.sidebar.slider("Tier 3 industries", 20, 100, 40)
big_m = st.sidebar.slider("Floor-violation penalty M", 100, 1000, 500, 50)
st.sidebar.subheader("Corridor capacity (% of nominal)")
cap_scale = {k: st.sidebar.slider(M.CORRIDOR_NAME[k], 5, 100, 100) / 100 for k in range(1, 6)}
st.sidebar.subheader("Your own data (optional)")
up_d = st.sidebar.file_uploader("Monthly demand CSV (A,B,P1..P4,I1,I2)", type="csv")
up_s = st.sidebar.file_uploader("Monthly supply CSV (column: supply)", type="csv")

demand = M.default_demand()
supply = list(M.SUPPLY)
try:
    if up_d is not None:
        d = pd.read_csv(up_d)[M.NODES]
        assert len(d) == 12
        d.index = MONTHS
        demand = d
    if up_s is not None:
        s = pd.read_csv(up_s)["supply"].tolist()
        assert len(s) == 12
        supply = s
except Exception as e:  # noqa: BLE001
    st.sidebar.error(f"Upload ignored: {e}")

P = M.Params(supply_pct=supply_pct, demand_pct=demand_pct, gas_cost=gas_cost, pen_png=pen_png,
             pen_cng=pen_cng, pen_ind=pen_ind, big_m=big_m, cap_scale=cap_scale, supply=supply, demand=demand)


def pkey(p):
    return (p.supply_pct, p.demand_pct, p.gas_cost, p.pen_png, p.pen_cng, p.pen_ind, p.big_m,
            tuple(p.cap_scale.items()), tuple(p.supply), p.demand.to_json())


@st.cache_data(show_spinner="Solving LP...")
def solved(_p, key):
    df, raw = M.solve_all(_p)
    return df, raw, M.corridor_table(_p, raw)


@st.cache_data(show_spinner="Running corridor-wise sensitivity (LP)...")
def sweep(_p, key):
    return M.corridor_sweep(_p)


@st.cache_data(show_spinner="Running one-way sensitivity...")
def oneway(_p, key, name, values):
    return M.one_way(_p, name, list(values))


@st.cache_data
def esc(_p, key):
    return M.escalation(_p)


K = pkey(P)
df, raw, ct = solved(P, K)
f0 = lambda x: f"{x:,.0f}"  # noqa: E731


# ----------------------------------------------------------------- figures
def network_fig(util):
    pos = {"G": (0, 1.5), "A": (2, 3), "B": (4, 3), "P12": (2, 1.5), "P34": (4, 1.5), "I": (2, 0)}
    names = {"G": "City Gate", "A": "CNG A", "B": "CNG B", "P12": "PNG P1,P2", "P34": "PNG P3,P4", "I": "Industry I1,I2"}
    lines = {1: ("G", "A"), 2: ("A", "B"), 3: ("G", "P12"), 4: ("P12", "P34"), 5: ("G", "I")}
    fig = go.Figure()
    for k, (a, b) in lines.items():
        u = util[k - 1]
        col = RED if u >= 0.99 else (ORANGE if u > 0.6 else TEAL)
        (x0, y0), (x1, y1) = pos[a], pos[b]
        fig.add_annotation(x=x1 - .25 * (x1 - x0) / max(abs(x1 - x0), 1e-9) * .5, y=y1, ax=x0 + .4, ay=y0, xref="x", yref="y",
                           axref="x", ayref="y", showarrow=True, arrowhead=3, arrowwidth=2 + 6 * u, arrowcolor=col)
        fig.add_annotation(x=(x0 + x1) / 2 + .2, y=(y0 + y1) / 2 + .18, showarrow=False,
                           text=f"C{k} {u * 100:.0f}%", font=dict(size=13, color=col))
    fig.add_trace(go.Scatter(x=[p[0] for p in pos.values()], y=[p[1] for p in pos.values()], mode="markers+text",
                             text=list(names.values()), textposition="middle center",
                             marker=dict(size=70, color="white", line=dict(width=2, color=TEAL)), hoverinfo="text"))
    fig.update_xaxes(visible=False, range=[-.8, 4.8]); fig.update_yaxes(visible=False, range=[-.7, 3.6])
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    return fig


def monthly_fig(d):
    fig = go.Figure()
    fig.add_bar(x=d["Month"], y=d["Supply"], name="Supply", marker_color=TEAL)
    fig.add_bar(x=d["Month"], y=d["Demand"], name="Demand", marker_color=ORANGE)
    fig.add_bar(x=d["Month"], y=d["Shortage"], name="Shortage", marker_color=RED)
    fig.update_layout(barmode="group", height=340, xaxis_title="Month", yaxis_title="SCM", margin=dict(t=20))
    return fig


def heat_fig(raw_, p):
    z = [[100 * r["flows"][k] / p.cap(k) for r in raw_] for k in range(1, 6)]
    fig = go.Figure(go.Heatmap(z=z, x=MONTHS, y=[M.CORRIDOR_NAME[k] for k in range(1, 6)], colorscale="Oranges",
                               zmin=0, zmax=100, text=[[f"{v:.0f}" for v in row] for row in z], texttemplate="%{text}",
                               colorbar=dict(title="% cap")))
    fig.update_layout(height=320, margin=dict(t=20), xaxis_title="Month")
    return fig


def sweep_fig(sw):
    fig = go.Figure()
    for k in range(1, 6):
        s = sw[sw["k"] == k]
        fig.add_scatter(x=s["Capacity %"], y=s["Total cost"], mode="lines+markers", name=M.CORRIDOR_NAME[k])
    fig.update_layout(height=400, xaxis_title="Corridor capacity (% of current setting)", yaxis_title="Annual cost (Rs)",
                      xaxis_autorange="reversed", margin=dict(t=20))
    return fig


def tornado_fig(p, key):
    base = df["Cost (Rs)"].sum()
    rows = []
    for label, name, lo, hi in [("Supply", "supply_pct", p.supply_pct - 10, p.supply_pct + 10),
                                ("Demand", "demand_pct", p.demand_pct - 10, p.demand_pct + 10),
                                ("Gas cost", "gas_cost", p.gas_cost * .9, p.gas_cost * 1.1)]:
        r = oneway(p, key, name, (lo, hi))
        rows.append((label, r["Total cost"].iloc[0] - base, r["Total cost"].iloc[1] - base))
    rows.sort(key=lambda r: max(abs(r[1]), abs(r[2])))
    fig = go.Figure()
    fig.add_bar(y=[r[0] for r in rows], x=[r[1] for r in rows], orientation="h", name="-10%", marker_color=TEAL)
    fig.add_bar(y=[r[0] for r in rows], x=[r[2] for r in rows], orientation="h", name="+10%", marker_color=ORANGE)
    fig.update_layout(barmode="overlay", height=280, xaxis_title="Change in annual cost (Rs)", margin=dict(t=20))
    return fig


# ----------------------------------------------------------------- tabs
tabs = st.tabs(["Home", "Model", "Audit", "PNGRB & T4S", "LP Lab", "Sensitivity", "MGL Data", "Report"])

with tabs[0]:
    st.title("CGD Planning DSS")
    st.caption("Gas allocation & network optimization for city gas distribution · LP model · Case study: Mahanagar Gas Limited, Mumbai")
    c = st.columns(4)
    c[0].metric("Annual optimal cost", f"Rs {f0(df['Cost (Rs)'].sum())}")
    c[1].metric("Total shortage", f"{f0(df['Shortage'].sum())} SCM")
    c[2].metric("Months with floor breach", f"{int((df['Floor violation'] > 1).sum())} / 12")
    bind = ct[ct["Binding"]]["Corridor"].tolist()
    c[3].metric("Binding corridors", ", ".join(b.split()[0] for b in bind) if bind else "None (supply binds)")
    st.subheader("Network (colour = corridor utilisation)")
    st.plotly_chart(network_fig((ct["Utilisation %"] / 100).tolist()), use_container_width=True)
    st.plotly_chart(monthly_fig(df), use_container_width=True)
    st.plotly_chart(heat_fig(raw, P), use_container_width=True)

with tabs[1]:
    st.header("Model & methodology")
    st.markdown("**Objective**")
    st.latex(r"\min Z=\sum_{t=1}^{12}\Big[\sum_{a}(c_a+g\,[a\ \text{leaves gate}])x_{a,t}+\sum_n p_n y_{n,t}+M\sum_n s_{n,t}\Big]")
    st.markdown("**Constraints**")
    st.latex(r"\sum_{a\in out(G)}x_{a,t}\le A_t\quad\text{(source)}")
    st.latex(r"\sum_{a\in in(n)}x_{a,t}-\sum_{a\in out(n)}x_{a,t}+y_{n,t}=D_{n,t}\quad\text{(node balance with transshipment)}")
    st.latex(r"\sum_{a\in k}x_{a,t}\le u_k\quad\text{(corridor capacity)}")
    st.latex(r"y_{n,t}\le(1-\alpha_n)D_{n,t}+s_{n,t}\quad\text{(elastic priority floor)},\qquad x,y,s\ge0")
    st.dataframe(pd.DataFrame({"Corridor": [M.CORRIDOR_NAME[k] for k in range(1, 6)],
                               "Capacity (SCM/mo)": [M.CORRIDOR_CAP[k] for k in range(1, 6)],
                               "Cost (Rs/SCM)": [M.CORRIDOR_COST[k] for k in range(1, 6)]}), hide_index=True)
    st.dataframe(pd.DataFrame({"Tier": [1, 2, 3], "Customer": ["PNG households", "CNG stations", "Industries"],
                               "Floor": ["95%", "90%", "80%"], "Canvas penalty": [20, 15, 10],
                               "Used here (Rs/SCM)": [pen_png, pen_cng, pen_ind]}), hide_index=True)

with tabs[2]:
    st.header("Canvas audit")
    st.markdown("""
1. **Node balance ignored transshipment**: B is fed through A, P3/P4 through P1/P2. Fixed: inflow - outflow + shortage = demand.
2. **Shortage totals do not reconcile**: monthly row sums to 24,500 SCM; the summary says 34,500 SCM.
3. **Month 1 shortage too low**: demand 13,500 vs supply 11,000 means at least 2,500 SCM short; the canvas shows 1,200.
4. **Hard floors infeasible in Month 1**: 12,225 SCM needed vs 11,000 available. Fixed with elastic floors (penalty M).
5. **Corridors 3 and 5 are not bottlenecks** with canvas data (peak use 57% and 30%); supply is the binding limit.
6. **CNG station B floor** is 90% in the table but 0.80 in the code.
7. **No gas purchase cost in the objective**, so the 2-10% escalation scenario could not change anything.
8. **Penalties of Rs 10-20/SCM are below delivered cost** (~Rs 34+/SCM), so a minimiser would under-deliver. Re-scaled to 60/50/40.
""")

with tabs[3]:
    st.header("PNGRB policy & T4S framework")
    st.caption("Titles as published by PNGRB; check pngrb.gov.in for the latest consolidated amendment before citing a clause.")
    st.dataframe(pd.DataFrame([
        ("PNGRB Act, 2006", "Establishes the Board: CGD authorisation, common/contract carrier, customer protection"),
        ("T4S: Technical Standards and Specifications including Safety Standards for City or Local Natural Gas Distribution Networks Regulations, 2008", "Design/operating/safety rules for pipelines and CNG stations; source of pressure-loss and sizing limits"),
        ("Authorising Entities to Lay, Build, Operate or Expand CGD Networks Regulations, 2008", "Geographical-area authorisation, minimum work programme, service obligations; capex and break-even context"),
        ("Integrity Management System (IMS) for CGD Networks Regulations", "Risk-based inspection/maintenance; network reliability"),
        ("ERDMP Codes of Practice Regulations", "Emergency response; scarcity/outage scenarios"),
        ("Natural Gas Pipeline Tariff Regulations, 2008", "Transport tariff method; informs corridor cost"),
        ("Access Code for Common/Contract Carrier Natural Gas Pipelines Regulations, 2008", "Open access and capacity booking; supply availability"),
        ("Government priority for domestic PNG and CNG (transport)", "Basis for Tier 1/Tier 2 ordering; verify the current MoPNG order"),
    ], columns=["Instrument", "Relevance to the DSS"]), hide_index=True, use_container_width=True)

with tabs[4]:
    st.header("LP Lab")
    st.plotly_chart(monthly_fig(df), use_container_width=True)
    m = st.select_slider("Inspect month", options=MONTHS, value=12)
    r = raw[m - 1]
    nd = pd.DataFrame({"Node": M.NODES, "Demand": [r["delivered"][n] + r["y"][n] for n in M.NODES],
                       "Delivered": [r["delivered"][n] for n in M.NODES], "Shortage": [r["y"][n] for n in M.NODES]})
    fig = go.Figure()
    fig.add_bar(x=nd["Node"], y=nd["Delivered"], name="Delivered", marker_color=TEAL)
    fig.add_bar(x=nd["Node"], y=nd["Shortage"], name="Shortage", marker_color=RED)
    fig.update_layout(barmode="stack", height=320, margin=dict(t=20), title=f"Month {m}: delivered vs shortage by node")
    st.plotly_chart(fig, use_container_width=True)
    cost_fig = go.Figure()
    for col, colr in [("Gas cost", TEAL), ("Transport", GREEN), ("Penalty", RED)]:
        cost_fig.add_bar(x=df["Month"], y=df[col], name=col, marker_color=colr)
    cost_fig.update_layout(barmode="stack", height=300, title="Cost composition (Rs)", margin=dict(t=40))
    st.plotly_chart(cost_fig, use_container_width=True)
    st.subheader("Corridors")
    st.dataframe(ct.round(2), hide_index=True, use_container_width=True)
    st.subheader("Monthly results")
    st.dataframe(df.round(1), hide_index=True, use_container_width=True)

with tabs[5]:
    st.header("Sensitivity analysis")
    sw = sweep(P, K)
    st.subheader("Corridor-wise sensitivity (one corridor cut at a time)")
    st.plotly_chart(sweep_fig(sw), use_container_width=True)
    pv = sw.pivot(index="Capacity %", columns="Corridor", values="Total cost").sort_index(ascending=False)
    st.dataframe(pv.round(0), use_container_width=True)
    pvs = sw.pivot(index="Capacity %", columns="Corridor", values="Avg shadow (Rs/SCM)").sort_index(ascending=False)
    st.markdown("**Average corridor shadow price (Rs/SCM saved per extra SCM/month of capacity)**")
    st.dataframe(pvs.round(2), use_container_width=True)
    st.subheader("Tornado: +/-10% in each driver")
    st.plotly_chart(tornado_fig(P, K), use_container_width=True)
    a, b = st.columns(2)
    with a:
        st.markdown("**Supply sweep**")
        s1 = oneway(P, K, "supply_pct", (-30, -20, -10, 0, 10, 20))
        st.plotly_chart(go.Figure(go.Scatter(x=s1["supply_pct"], y=s1["Total cost"], mode="lines+markers", line_color=TEAL)).update_layout(height=300, xaxis_title="Supply change %", yaxis_title="Annual cost", margin=dict(t=10)), use_container_width=True)
    with b:
        st.markdown("**Demand sweep**")
        s2 = oneway(P, K, "demand_pct", (-10, 0, 10, 20, 30, 40))
        st.plotly_chart(go.Figure(go.Scatter(x=s2["demand_pct"], y=s2["Total cost"], mode="lines+markers", line_color=ORANGE)).update_layout(height=300, xaxis_title="Demand change %", yaxis_title="Annual cost", margin=dict(t=10)), use_container_width=True)
    st.subheader("Scenario 2: gas-cost escalation")
    e = esc(P, K)
    st.dataframe(e.round(2), hide_index=True, use_container_width=True)
    st.plotly_chart(go.Figure(go.Bar(x=e["Escalation %"].astype(str) + "%", y=e["Delta"], marker_color=ORANGE)).update_layout(height=280, yaxis_title="Extra annual cost (Rs)", margin=dict(t=10)), use_container_width=True)

with tabs[6]:
    st.header("MGL Mumbai evidence base")
    st.caption("Source-verified annual data (FY2023-24 to FY2025-26). Monthly values are not publicly disclosed and are not estimated.")
    st.dataframe(pd.DataFrame({"FY": ["2023-24", "2024-25", "2025-26"], "CNG (mn SCM)": [948.17, 1112.23, 1192.55],
                               "Domestic PNG": [190.33, 202.97, 215.44], "Industry/Commercial PNG": [182.50, 230.73, 265.44],
                               "Total": [1321.00, 1545.93, 1673.43], "MMSCMD": [3.609, 4.235, 4.585]}), hide_index=True)
    st.dataframe(pd.DataFrame({"31 March": [2023, 2024, 2025, 2026], "CNG stations": [313, 347, 385, 518],
                               "Connected households (m)": [2.17, 2.50, 2.83, 3.21], "I&C customers": [4558, 4769, 5105, 5924]}), hide_index=True)
    st.info("Canvas demand (~13,500 SCM/month) is a toy scale; MGL sells roughly 140 million SCM/month. Rescale before presenting as real.")


def build_report():
    parts = [f"<h1>CGD Gas Allocation LP Report</h1><p>Generated {date.today():%d %b %Y} from the CGD Planning DSS (SciPy HiGHS). Academic demo data.</p>"]
    parts.append("<h2>Parameters</h2>" + pd.DataFrame({"Parameter": ["Supply change %", "Demand change %", "Gas cost Rs/SCM", "Penalties PNG/CNG/IND", "M", "Corridor capacity %"],
        "Value": [supply_pct, demand_pct, gas_cost, f"{pen_png}/{pen_cng}/{pen_ind}", big_m, ", ".join(f"{v * 100:.0f}" for v in cap_scale.values())]}).to_html(index=False))
    parts.append(f"<h2>Headline</h2><p>Annual cost <b>Rs {f0(df['Cost (Rs)'].sum())}</b>; shortage <b>{f0(df['Shortage'].sum())} SCM</b>; floors breached in <b>{int((df['Floor violation'] > 1).sum())}/12</b> months.</p>")
    first = True
    for title, fg in [("Monthly performance", monthly_fig(df)), ("Corridor utilisation (%)", heat_fig(raw, P)), ("Corridor-wise sensitivity", sweep_fig(sw))]:
        parts.append(f"<h2>{title}</h2>" + fg.to_html(full_html=False, include_plotlyjs="cdn" if first else False)); first = False
    parts.append("<h2>Corridors</h2>" + ct.round(2).to_html(index=False))
    parts.append("<h2>Corridor sweep: annual cost (Rs)</h2>" + pv.round(0).to_html())
    parts.append("<h2>Monthly results</h2>" + df.round(1).to_html(index=False))
    rk = sw[sw["Capacity %"] == 30].sort_values("Delta vs full", ascending=False)
    parts.append(f"<h2>Findings</h2><ul><li>Most critical corridor: <b>{rk.iloc[0]['Corridor']}</b> (30% capacity adds Rs {f0(rk.iloc[0]['Delta vs full'])}). Least critical: {rk.iloc[-1]['Corridor']}.</li>"
                 f"<li>{'Binding: ' + ', '.join(bind) if bind else 'No corridor binds at current settings; source supply is the limiting resource.'}</li>"
                 "<li>Months 2-11 demand is interpolated unless a CSV is uploaded.</li></ul>")
    css = "<style>body{font:15px system-ui;max-width:1000px;margin:24px auto;padding:0 16px}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #ccc;padding:4px 8px}h1,h2{color:#0b6e8a}</style>"
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>CGD LP Report</title>{css}</head><body>{''.join(parts)}</body></html>"


with tabs[7]:
    st.header("Report")
    st.caption("Generated from the live LP using the current sidebar settings.")
    html = build_report()
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Monthly", index=False); ct.to_excel(xw, sheet_name="Corridors", index=False); sw.to_excel(xw, sheet_name="Corridor sweep", index=False)
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download report (.html)", html, "CGD_LP_Report.html", "text/html")
    c2.download_button("Download monthly data (.csv)", df.to_csv(index=False), "CGD_LP_Monthly.csv", "text/csv")
    c3.download_button("Download workbook (.xlsx)", xbuf.getvalue(), "CGD_LP_Results.xlsx")
    st.components.v1.html(html, height=900, scrolling=True)
