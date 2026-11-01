from pathlib import Path

def load(name):
    return Path(__file__).with_name(name + '.txt').read_text(encoding='utf-8')
