"""Source-scoped identity: masked names and text prefixes are not review IDs."""
def review_identity(row):
    source = 'smartstore' if row.get('platform') == 'smartstore' else str(row.get('platform') or 'direct')
    for field in ('review_no', 'review_id', 'id'):
        if row.get(field) not in (None, ''):
            return (source, field, str(row[field]))
    return (source, 'legacy', str(row.get('date') or ''),
            str(row.get('author') or ''), str(row.get('product') or ''),
            str(row.get('title') or ''), str(row.get('content') or ''),
            str(row.get('score') or ''))
