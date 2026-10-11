"""Bounded typography checks; never rewrite outputs or infer semantic truth."""
import re

SUBJECT_BYTES = 160
BODY_BYTES = 2200
# Preserve ordinary English typography; no Unicode-to-ASCII transliteration.
PUNCTUATION = '\u2018\u2019\u201c\u201d\u2013\u2014\u2026'
SUBJECT_PATTERN = r'^[\x20-\x7e\u2018\u2019\u201c\u201d\u2013\u2014\u2026]{0,160}$'
BODY_PATTERN = r'^[\x09\x0a\x0d\x20-\x7e\u2018\u2019\u201c\u201d\u2013\u2014\u2026]{0,2200}$'
_CONTRACTIONS = {
    'i': ('m','ll','ve','d'), 'you': ('re','ve','ll','d'),
    'we': ('re','ve','ll','d'), 'they': ('re','ve','ll','d'),
    'he': ('s','ll','d'), 'she': ('s','ll','d'), 'it': ('s','ll','d'),
    'there': ('s','ll','d'), 'that': ('s','ll','d'), 'let': ('s',),
    **{stem: ('t',) for stem in ('don','doesn','didn','isn','aren','wasn','weren',
                               'hasn','haven','hadn','couldn','wouldn','shouldn','can','won')},
}


def broken_apostrophe_fragments(content, parent=None):
    """Flag characteristic newline corruption, not all grammatical errors.

    Parent possessives/contractions add exact lexical checks; missing/rephrased
    words are not silently restored, normalized or declared equivalent.
    """
    text = content['subject']+'\n'+content['body']
    pairs = {(stem,suffix) for stem,suffixes in _CONTRACTIONS.items() for suffix in suffixes}
    if parent:
        old = parent['subject']+'\n'+parent['body']
        pairs.update((m[0].casefold(),m[1].casefold()) for m in
                     re.findall(r"\b([A-Za-z]+)['\u2018\u2019]([A-Za-z]+)\b", old))
    flags=[]
    for stem,suffix in sorted(pairs):
        pattern=r'\b'+re.escape(stem)+r"[ \t]*['\u2018\u2019]?[ \t]*(?:\r\n|\n|\r)[ \t]*['\u2018\u2019]?[ \t]*"+re.escape(suffix)+r'\b'
        flags.extend(m.group(0) for m in re.finditer(pattern,text,re.I))
    return sorted(set(flags))


def profile_valid(content):
    """Character allowlist plus UTF-8 byte ceilings bound accepted review input."""
    if not isinstance(content,dict) or set(content)!={'subject','body'}:
        return False
    for key,pattern,limit in [('subject',SUBJECT_PATTERN,SUBJECT_BYTES),('body',BODY_PATTERN,BODY_BYTES)]:
        value=content[key]
        if not isinstance(value,str) or not re.fullmatch(pattern,value) or len(value.encode('utf-8'))>limit:
            return False
    return not broken_apostrophe_fragments(content)
