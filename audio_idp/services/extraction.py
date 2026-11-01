import re
from audio_idp.providers.bedrock import ask_json

def supporting_quote(transcript, quote):
    if not isinstance(quote, str) or not quote.strip():
        return None
    if quote in transcript:
        return quote
    # Only typography, letter case, and whitespace may differ; preserve source wording.
    quote = quote.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    pattern = pattern.replace("'", "['‘’]").replace('"', '["“”]')
    match = re.search(pattern, transcript, flags=re.IGNORECASE)
    return match.group(0) if match else None


def extract(client, model, transcript, fields):
    result = ask_json(client, model,
        'Return {"fields": {"configured_name": {"value": "text or null", "evidence": "exact transcript quote or null"}}}. '
        'Include every configured field, no additional fields. Values must be strings or null. '
        'Use null for information that is absent or uncertain. For each non-null value, copy a short, '
        'continuous quote directly from the transcript as evidence. Never paraphrase, translate, '
        'join separate passages, or insert ellipses into evidence.',
        {"fields": fields, "transcript": transcript})
    values = result.get("fields")
    if not isinstance(values, dict) or set(values) != {f["name"] for f in fields}:
        raise ValueError("Extracted fields do not match the configuration.")
    for value in values.values():
        if not isinstance(value, dict) or set(value) != {"value", "evidence"}:
            raise ValueError("Invalid field result.")
        if value["value"] is None:
            value["evidence"] = None
        elif not isinstance(value["value"], str):
            raise ValueError("Extracted values must be text or null.")
        else:
            quote = supporting_quote(transcript, value["evidence"])
            if quote is None:
                value.update(value=None, evidence=None, warning="Needs review: no matching transcript quote. Value withheld.")
            else:
                value["evidence"] = quote
    return values
