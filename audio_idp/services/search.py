"""Global indexed search, independent of the Streamlit view."""
def search(store, query, *, kind=None, batch=None, page=1):
    if page < 1:
        raise ValueError('Search pages start at one.')
    return store.search(query, kind, batch, (page-1)*20)
