from __future__ import annotations

from urllib.parse import quote

PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def build_cid_url(query: str) -> str:
    return f"{PUBCHEM_BASE_URL}/compound/name/{quote(query, safe='')}/cids/JSON"


def build_property_url(cid: int) -> str:
    properties = ",".join(
        [
            "MolecularFormula",
            "MolecularWeight",
            "CanonicalSMILES",
            "IsomericSMILES",
            "InChIKey",
        ]
    )
    return f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/{properties}/JSON"


def build_synonym_url(cid: int) -> str:
    return f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/synonyms/JSON"
