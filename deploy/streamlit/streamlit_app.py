"""Funding Navigator on Streamlit.

Streamlit Community Cloud runs a Streamlit script, not our FastAPI server, so this page serves the site in dist/ (Explore, Statistics,
My saved) as a Streamlit component. The data is in dist/data: nothing here needs a backend, a database or a key. The parts of the site
that need the backend (AI search and chat) are switched off in this version (see embed.js and embed.css). The full app, with AI, runs
locally: see the README at the top of the repository.
"""

import shutil
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
DIST = HERE.parents[1] / "dist"

st.set_page_config(page_title="Funding Navigator", page_icon="🌿", layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource(show_spinner="Loading the funding data…")
def site_folder() -> str:
    """A copy of dist/ whose index.html also loads the Streamlit adapter; dist/ itself is not touched."""
    target = Path(tempfile.mkdtemp(prefix="funding-navigator-")) / "site"
    shutil.copytree(DIST, target)
    for name in ("embed.js", "embed.css"):
        shutil.copy(HERE / name, target / name)
    index = target / "index.html"
    html = index.read_text(encoding="utf-8")
    if "</head>" not in html:
        raise RuntimeError("dist/index.html has no </head>")
    index.write_text(
        html.replace(
            "</head>", '  <link rel="stylesheet" href="embed.css">\n  <script src="embed.js"></script>\n</head>', 1
        ),
        encoding="utf-8",
    )
    return str(target)


# The site fills the window: hide Streamlit's own header, footer and padding.
st.markdown(
    """
    <style>
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer, #MainMenu { display: none !important; }
    .block-container, [data-testid="stMainBlockContainer"] { padding: 0 !important; max-width: 100% !important; }
    [data-testid="stAppViewContainer"] > .main, [data-testid="stMain"] { overflow: hidden; }
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: #f8f7f2 !important; color-scheme: light; }
    [data-testid="stVerticalBlock"] { gap: 0 !important; }
    .stApp iframe { display: block; width: 100%; height: 100vh !important; height: 100dvh !important; border: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

site = components.declare_component("funding_navigator_site", path=site_folder())
site(key="site", default=None)
