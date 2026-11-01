import streamlit as st
from audio_idp.config import DATA
from audio_idp.persistence.database import Store
from audio_idp.workflow.coordinator import Workspace

@st.cache_resource
def workspace():
    return Workspace(Store(DATA), automatic=True)
