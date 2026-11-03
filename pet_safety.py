"""Owner supplied care facts; no diagnosis, treatment or verification inference."""
import re

FIELDS = ('vaccinations', 'allergies', 'medications', 'behavior', 'emergencyName', 'emergencyPhone')
LIMITS = {**dict.fromkeys(FIELDS[:4], 2000), 'emergencyName': 120, 'emergencyPhone': 16}


def validate(pet):
    result = {}
    for field in FIELDS:
        value = pet.get(field)
        value = '' if value is None else value
        if not isinstance(value, str) or len(value)>LIMITS[field] or any(ord(c)<32 and c not in '\n\t' for c in value):
            raise ValueError('Hayvon parvarishi ma’lumoti noto‘g‘ri')
        result[field] = value.strip()
    if result['emergencyPhone'] and not re.fullmatch(r'\+[1-9][0-9]{7,14}', result['emergencyPhone']):
        raise ValueError('Favqulodda telefonni + va davlat kodi bilan kiriting')
    return result
