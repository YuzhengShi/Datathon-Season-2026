# Funding Navigator on Streamlit

The site in `dist/` (Explore, Statistics, My saved) as a Streamlit app. Streamlit Community Cloud runs a Streamlit script, not our FastAPI server, so `streamlit_app.py` serves `dist/` as a Streamlit component. It needs no backend, database or key: the data is `dist/data/opportunities.json`.

**Not in this version:** AI search and chat. They need the backend and an LLM key, so they are hidden here. The full app, with AI, runs locally (see the README at the top of the repository).

## Deploy (Streamlit Community Cloud)

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with the GitHub account that can read the repository.
2. New app: repository `YuzhengShi/Datathon-Season-2026`, branch `main`, main file path `deploy/streamlit/streamlit_app.py`, then Deploy. A prefilled link: <https://share.streamlit.io/deploy?repository=YuzhengShi/Datathon-Season-2026&branch=main&mainModule=deploy/streamlit/streamlit_app.py>
3. Nothing else is needed (no secrets). Free apps go to sleep after a while without visitors: open the link once before a demo to wake it. A push to `main` redeploys the app by itself.

## Run it locally

```powershell
pip install -r deploy/streamlit/requirements.txt
streamlit run deploy/streamlit/streamlit_app.py
```

## Check it

With the app running, this opens it in Chrome on a desktop and on a phone window, and checks the main paths, that the AI buttons are hidden and that every page scrolls (mouse wheel and swipe). It also accepts the address of the deployed app.

```powershell
node tests/e2e/streamlit.mjs --base=http://127.0.0.1:8501
```

## How it works

- `streamlit_app.py` copies `dist/` to a temporary folder, adds `embed.js` and `embed.css` to its `index.html`, and serves that folder with `components.declare_component(path=...)`. `dist/` itself is not changed. It also makes the frame as tall as the window and hides Streamlit's own header, footer and padding.
- Streamlit builds the frame of a component with `scrolling="no"`, so the frame's own viewport cannot scroll. `embed.css` makes the body the scroller instead and `embed.js` points the site's `scrollTo` calls at it.
- `embed.js` also keeps the site in its static mode (`/api/...` calls fail at once), switches the search box to keyword search and tells Streamlit the frame is ready. `embed.css` hides the AI buttons.
