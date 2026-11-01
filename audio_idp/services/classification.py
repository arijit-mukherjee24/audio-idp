from audio_idp.providers.bedrock import ask_json
from audio_idp.services.definitions import validate_classes
UNCLASSIFIED = "Unclassified"

def classify(client, model, transcript, classes):
    validate_classes(classes)
    result = ask_json(client, model,
        'Determine the primary business purpose of the transcript. The configured classes are approved candidates; '
        'compare their inclusion criteria and select exactly one, using its exact name. Do not invent, rename or merge classes. '
        'Prefer a matching specific class over a vague alternative. Use Unclassified only when none genuinely fits or the text '
        'is insufficient. Explain the decisive transcript facts and why the selected definition fits. '
        'Return {"class": "exact configured name or Unclassified", "reason": "brief factual explanation"}.',
        {"classes": [{"name": c["name"], "description": c["description"]} for c in classes],
         "transcript": transcript})
    if result.get("class") not in [c["name"] for c in classes] + [UNCLASSIFIED]:
        raise ValueError("Bedrock returned an unknown class.")
    if not isinstance(result.get("reason"), str):
        raise ValueError("Bedrock returned an invalid classification reason.")
    return result
