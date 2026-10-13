"""Funding Navigator on Streamlit.

Streamlit Community Cloud runs a Streamlit script, not our FastAPI server, so this page serves the site in dist/ (Explore, Statistics,
My saved) as a Streamlit component. The data is in dist/data: nothing here needs a backend, a database or a key. The parts of the site
that need the backend (AI search and chat) are switched off in this version (see embed.js and embed.css). The full app, with AI, runs
locally: see the README at the top of the repository.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
DIST = HERE.parents[1] / "dist"
ADAPTER = ("embed.js", "embed.css")

st.set_page_config(page_title="Funding Navigator", page_icon="🌿", layout="wide", initial_sidebar_state="collapsed")


def site_version() -> str:
    """A short code that changes whenever a file of the site or of the adapter changes.

    Streamlit keeps cached values, and the temporary copy of the site made below, across the hot reload that follows a push to GitHub.
    Without this code a redeployed app would go on serving the files of the previous version.
    """
    digest = hashlib.sha1()
    for path in sorted(p for p in DIST.rglob("*") if p.is_file()) + [HERE / name for name in ADAPTER]:
        size = path.stat().st_size
        digest.update(f"{path.name}|{size}|".encode())
        digest.update(path.read_bytes() if size <= 1_000_000 else str(path.stat().st_mtime_ns).encode())
    return digest.hexdigest()[:10]


@st.cache_resource(show_spinner="Loading the funding data…")
def site_folder(version: str) -> str:
    """A copy of dist/ whose index.html also loads the Streamlit adapter; dist/ itself is not touched."""
    target = Path(tempfile.mkdtemp(prefix=f"funding-navigator-{version}-")) / "site"
    shutil.copytree(DIST, target)
    for name in ADAPTER:
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

# The component is named after the version, so a browser that kept files of an earlier version asks for new ones.
current = site_version()
site = components.declare_component(f"funding_navigator_site_{current}", path=site_folder(current))
site(key="site", default=None)
