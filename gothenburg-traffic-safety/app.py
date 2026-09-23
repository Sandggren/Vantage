"""Entry point for the Gothenburg Traffic Safety app.

Run with `streamlit run app.py`. This file only defines the sidebar
navigation (so the main page is labelled "Dashboard" rather than after
this file's name); each page's content lives in its own file.
"""

import streamlit as st

import config

# Shown at the top of the sidebar on every page; the shield alone is used
# when the sidebar is collapsed.
st.logo(config.LOGO_WIDE_PATH, size="large", icon_image=config.LOGO_ICON_PATH)

# Page files live in app_pages/, not pages/: Streamlit treats a folder named
# "pages" as an old-style multipage app and can open those files directly,
# bypassing this navigation (sidebar shows "app", no logo).
pages = [
    st.Page("dashboard.py", title="Dashboard", default=True),
    st.Page("app_pages/1_Report_Near_Miss.py", title="Report Near Miss"),
    st.Page("app_pages/2_Route_Check.py", title="Route Check"),
]

st.navigation(pages).run()
