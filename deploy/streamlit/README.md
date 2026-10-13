# Funding Navigator on Streamlit

The site in `dist/` (Explore, Statistics, My saved) as a Streamlit app. Streamlit Community Cloud runs a Streamlit script, not our FastAPI server, so `streamlit_app.py` serves `dist/` as a Streamlit component. It needs no backend, database or key: the data is `dist/data/opportunities.json`.

**Not in this version:** AI search and chat. They need the backend and an LLM key, so they are hidden here. The full app, with AI, runs locally (see the README at the top of the repository).

## Deploy (Streamlit Community Cloud)

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with the GitHub account that can read the repository.
2. New app: repository `YuzhengShi/Datathon-Season-2026`, branch `main`, main file path `deploy/streamlit/streamlit_app.py`, then Deploy. A prefilled link: <https://share.streamlit.io/deploy?repository=YuzhengShi/Datathon-Season-2026&branch=main&mainModule=deploy/streamlit/streamlit_app.py>
3. Nothing else is needed (no secrets). Free apps go to sleep after a while without visitors: open the link once before a demo to wake it.

## Run it locally

```powershell
pip install -r deploy/streamlit/requirements.txt
streamlit run deploy/streamlit/streamlit_app.py
```

## How it works

- `streamlit_app.py` copies `dist/` to a temporary folder, adds `embed.js` and `embed.css` to its `index.html`, and serves that folder with `components.declare_component(path=...)`. `dist/` itself is not changed.
- `embed.js` tells Streamlit the frame is ready, makes it as tall as the window, switches the search box to keyword search and makes `/api/...` calls fail at once, so the site stays in its static mode. `embed.css` hides the AI buttons.
- Streamlit's own header, footer and padding are hidden so that the site fills the page.
