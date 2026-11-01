"""Streamlit entry point; processing and persistence are independent of the UI."""
import streamlit as st
from audio_idp.ui.session import workspace
from audio_idp.ui.layout import render

st.set_page_config(page_title='Audio IDP · Audio intelligence', page_icon='🎙️', layout='wide', initial_sidebar_state='collapsed')
render(workspace())
