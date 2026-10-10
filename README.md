# CGD Planning DSS: Gas Allocation & Network Optimization

Streamlit decision-support app for city gas distribution (CGD): a 12-month linear programme that allocates
scarce gas across CNG stations, PNG nodes and industries, with corridor-wise sensitivity, shadow prices,
PNGRB (incl. T4S) context and a downloadable report. Case study: Mahanagar Gas Limited (Mumbai).

## Files
| File | Purpose |
|---|---|
| `app.py` | Streamlit interface (tabs, charts, report downloads) |
| `model.py` | LP model (SciPy HiGHS), sensitivity and report data |
| `requirements.txt` | Python dependencies |
| `.streamlit/config.toml` | Theme/server settings |

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud via GitHub
1. Create a new GitHub repository (e.g. `cgd-planning-dss`), then upload ALL files in this folder
   (GitHub: *Add file > Upload files*; keep `.streamlit/config.toml` in its folder). Commit to `main`.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **Create app > Deploy a public app from GitHub**.
4. Choose your repository, branch `main`, main file path `app.py`. Click **Deploy**.
5. After a minute the app is live at `https://<your-app-name>.streamlit.app`. Every `git push` redeploys it.

## Using your own data
* Sidebar > **Upload monthly demand CSV**: columns `A,B,P1,P2,P3,P4,I1,I2`, 12 rows (months 1-12).
* Sidebar > **Upload monthly supply CSV**: one column named `supply`, 12 rows.
* Without uploads, Months 2-11 demand are linearly interpolated between canvas Month 1 and Month 12 (assumption).

## Model notes
* Node balance includes transshipment (gas to B passes through A; gas to P3/P4 passes through P1/P2).
* Service floors are elastic (penalty M), so months where supply cannot meet the floors still solve.
* Shortage penalties must exceed delivered cost (gas + transport); defaults are Rs 60/50/40 per SCM.
* Data are academic demo values, not operational MGL planning figures.
