"""Tokenisation, stemming, stop-words and synonym groups."""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")

STOP = set("""
a an the and or but if so of in on at by for from to with as is are was were be been am
do does did can could should would will may might must how what when where which who why
i me my we our you your it its this that these those there here they them their he she
get got have has had any some more than then just also about into out up not no yes
need want please tell show give know like thing things way able new one them s t
""".split())

# Words an admin might use that the docs phrase differently.
# Each key maps to alternatives that count as a match (never the other way round
# unless listed). Kept deliberately small and auditable.
_RAW_SYNONYMS = {
    "forgot": ["reset"], "forgotten": ["reset"], "recover": ["reset"], "recovery": ["reset"],
    "locked": ["lockout", "unlock"], "unlock": ["lockout", "locked"],
    "price": ["billing", "invoice"], "pricing": ["billing", "invoice"], "cost": ["billing", "invoice"],
    "charge": ["billing", "invoice"], "charged": ["billing", "invoice"],
    "payment": ["billing", "invoice"], "pay": ["billing", "payment"],
    "bill": ["invoice", "billing"], "billed": ["invoice", "billing"], "receipt": ["invoice"],
    "download": ["export"], "extract": ["export"],
    "cap": ["limit"], "size": ["gb", "limit"], "maximum": ["limit"], "max": ["limit", "gb"], "quota": ["limit"],
    "member": ["user"], "staff": ["user"], "employee": ["user"], "people": ["user"],
    "permission": ["role"], "access": ["role"],
    "login": ["sign"], "log": ["sign"], "signin": ["sign"],
    "remove": ["delete", "deactivate"], "delete": ["remove", "deactivate"],
    "2fa": ["mfa"], "mfa": ["multi", "factor", "authentication"],
    "saml": ["sso"], "idp": ["identity", "provider"],
    "cancel": ["refund"], "money": ["refund"],
}


def stem(w: str) -> str:
    """Very light suffix stripper (consistent on both sides of the match)."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            return w[:-1] if len(w) > 4 and w.endswith("e") else w
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):   # expire/expired/expires, invoice/invoiced -> same stem
        w = w[:-1]
    return w


def tokenize(text: str, drop_stop: bool = True) -> list[str]:
    out = []
    for t in _TOKEN.findall(text.lower()):
        if drop_stop and t in STOP:
            continue
        out.append(stem(t))
    return out


SYNONYMS: dict[str, list[str]] = {
    stem(k): [stem(v) for v in vs] for k, vs in _RAW_SYNONYMS.items()
}
