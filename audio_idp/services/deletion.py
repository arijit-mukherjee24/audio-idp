"""Deletion entry points shared by entity menus and bulk operations."""
def delete_entities(store, ids):
    for id in dict.fromkeys(ids):
        store.delete(id)

def reset_workspace(workspace, remove_models=False):
    with workspace.store.lock:
        if remove_models and any(not f.done() for f in workspace.jobs.futures):
            raise ValueError('Wait for running operations to finish before removing model files.')
        workspace.store.reset(remove_models)
