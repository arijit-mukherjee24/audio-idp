UNCLASSIFIED = "Unclassified"
from audio_idp.domain.validation import definition

def validate_classes(classes):
    if not isinstance(classes, list) or not classes:
        raise ValueError("Create at least one class.")
    names = set()
    for item in classes:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('description'), str):
            raise ValueError('Each class needs a text name and description.')
        definition(item.get('name', ''), item.get('description', ''), is_class=True)
        name = item.get("name", "").strip()
        if not name or name.casefold() in names or name == UNCLASSIFIED:
            raise ValueError("Class names must be unique, nonempty, and not Unclassified.")
        names.add(name.casefold())
        if not item.get("description", "").strip():
            raise ValueError(f"Describe when to use class {name}.")
        fields = item.get("fields", [])
        if not isinstance(fields, list):
            raise ValueError("Fields must be a list.")
        field_names = set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get('name'), str) or not isinstance(field.get('description'), str) or not field['description'].strip():
                raise ValueError('Each field needs a text name and description.')
            key = field.get("name", "").strip()
            if not key or key.casefold() in field_names:
                raise ValueError(f"Field names in {name} must be unique and nonempty.")
            field_names.add(key.casefold())
    return classes
