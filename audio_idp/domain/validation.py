def definition(name, description, *, is_class=False):
    name, description = str(name).strip(), str(description).strip()
    if not name or not description:
        raise ValueError('Name and description are required.')
    if is_class and (len(name) > 80 or len(description) > 400):
        raise ValueError('Class names allow 80 characters; descriptions allow 400.')
    if is_class and name.casefold() == 'unclassified':
        raise ValueError('Unclassified is reserved for unmatched recordings.')
    return {'name': name, 'description': description}


def suggestions(result, key, *, is_class=False, limit=10, allow_empty=False):
    rows = result.get(key)
    minimum = 0 if allow_empty else 1
    if not isinstance(rows, list) or not minimum <= len(rows) <= limit:
        raise ValueError(f'Expected between {minimum} and {limit} {key}. Retry suggestions.')
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(row.get('description'), str):
            raise ValueError('Each suggestion needs a text name and description.')
        item = definition(row['name'], row['description'], is_class=is_class)
        if item['name'].casefold() in seen:
            raise ValueError('Duplicate suggestions returned. Retry suggestions.')
        seen.add(item['name'].casefold())
        output.append(item)
    return output
