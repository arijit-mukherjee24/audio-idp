import csv
import io

def export_csv(records):
    output_buffer = io.StringIO(newline="")
    writer = csv.writer(output_buffer)
    writer.writerow(["file", "class", "field", "value", "evidence", "review_note", "error"])
    def safe(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for record in records:
        fields = record.get("fields") or {"": {"value": "", "evidence": ""}}
        for name, value in fields.items():
            writer.writerow([safe(v) for v in [record["name"], record.get("class"), name,
                            value["value"], value["evidence"], value.get("warning"), record.get("error")]])
    return output_buffer.getvalue().encode("utf-8-sig")
