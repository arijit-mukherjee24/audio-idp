"""Load local settings without replacing explicit shell configuration."""
from dotenv import load_dotenv


def load_environment(path):
    # Credentials can contain '$'; do not interpolate other variables into them.
    return load_dotenv(dotenv_path=path,override=False,interpolate=False,encoding='utf-8-sig')
