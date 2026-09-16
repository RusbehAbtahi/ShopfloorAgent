import streamlit as st

from gui import run_gui


st.set_page_config(
    page_title="ShopfloorAgent",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

run_gui()
