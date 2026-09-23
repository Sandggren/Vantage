"""Entry point for the Gothenburg Traffic Safety app.

Run with `streamlit run app.py`. This file only defines the sidebar
navigation (so the main page is labelled "Dashboard" rather than after
this file's name); each page's content lives in its own file.
"""

import streamlit as st

pages = [
    st.Page("dashboard.py", title="Dashboard", default=True),
    st.Page("pages/1_Report_Near_Miss.py", title="Report Near Miss"),
    st.Page("pages/2_Route_Check.py", title="Route Check"),
]

st.navigation(pages).run()
