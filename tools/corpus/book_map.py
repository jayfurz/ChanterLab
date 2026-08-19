#!/usr/bin/env python3
"""Book map for the Ioannou Anastasimatarion PDF (Vasilikos corpus).

Scans every page's text layer + vector drawings and writes:
  /mnt/data/chant-corpus/scores/book_map.json          per-page inventory + sections
  /mnt/data/chant-corpus/scores/recording_page_map.json recording -> page-range proposals

Page facts recorded per page: n_drawings (all), n_fill / n_fill_red (filled
paths = notation; red = martyria/fthora/gorgon), n_images, printed page
number, header lines by font role, first lyric words, greek-ratio of the
lyric text (some PDFsam-merged source pages have a broken ToUnicode -> mojibake).

Font roles in this book:
  01-01ANNAKEFALEAUC*   running header (mode name / service name, alternating sides)
  00-02GenesisPt        big section titles
  00-03EcclesiaAthena*  rubrics / subtitles
  00-00RegGFSDidot      front matter (TOC; broken ToUnicode, but the ASCII
                        page-number ranges '5-94' etc. survive)
  01-132004ANNA2000     small = printed page number, large (>18pt) = drop-cap initials
  00-01SKAlexander*     lyrics

Section structure is derived twice (running headers vs TOC printed ranges)
and cross-checked. Usage: book_map.py [--pdf PATH] [--out DIR]
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter

sys.path.append('/mnt/data/code/byzorgan-web/training-prototype/omr/.venv/lib/python3.11/site-packages')
import fitz  # noqa: E402

DEFAULT_RAW = '/mnt/data/chant-corpus/raw/vasilikos'
DEFAULT_OUT = '/mnt/data/chant-corpus/scores'
PDF_NAME_NFC = 'Αναστασιματάριο-Ιωάννου.pdf'
CORPUS_JSON = '/mnt/data/chant-corpus/corpus.json'
AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus'}

MODE_ORDER = ['first', 'second', 'third', 'fourth',
              'plagal_first', 'plagal_second', 'varys', 'plagal_fourth']
MODE_LABEL = {
    'first': 'ΗΧΟΣ ΠΡΩΤΟΣ', 'second': 'ΗΧΟΣ ΔΕΥΤΕΡΟΣ', 'third': 'ΗΧΟΣ ΤΡΙΤΟΣ',
    'fourth': 'ΗΧΟΣ ΤΕΤΑΡΤΟΣ', 'plagal_first': 'ΗΧΟΣ ΠΛΑΓΙΟΣ Α',
    'plagal_second': 'ΗΧΟΣ ΠΛΑΓΙΟΣ Β', 'varys': 'ΗΧΟΣ ΒΑΡΥΣ',
    'plagal_fourth': 'ΗΧΟΣ ΠΛΑΓΙΟΣ Δ',
}
# audio dir/file name -> mode key
AUDIO_MODE = {
    'mode 1': 'first', 'mode 2': 'second', 'mode 3': 'third', 'mode 4': 'fourth',
    'mode plagal 1st': 'plagal_first', 'mode plagal 2nd': 'plagal_second',
    'mode grave': 'varys', 'mode plagal 4th': 'plagal_fourth',
}


def norm_greek(s):
    """uppercase, strip accents, unify the U+2206 increment glyph used for Δ"""
    s = s.replace('∆', 'Δ')
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.upper()


def classify_mode(text):
    t = norm_greek(text)
    if 'ΗΧΟΣ' not in t and 'ΠΛΑΓΙΟΣ' not in t and 'ΒΑΡΥΣ' not in t:
        return None
    if 'ΠΛΑΓΙΟΣ' in t:
        if 'ΠΡΩΤΟΥ' in t or re.search(r'ΠΛΑΓΙΟΣ\s+Α', t):
            return 'plagal_first'
        if re.search(r'ΠΛΑΓΙΟΣ\s+(ΤΟΥ\s+)?(Β|ΔΕΥΤΕΡΟΥ)', t):
            return 'plagal_second'
        if re.search(r'ΠΛΑΓΙΟΣ\s+(ΤΟΥ\s+)?(Δ|ΤΕΤΑΡΤΟΥ)', t):
            return 'plagal_fourth'
        return None
    if 'ΒΑΡΥΣ' in t:
        return 'varys'
    if 'ΠΡΩΤΟΣ' in t:
        return 'first'
    if 'ΔΕΥΤΕΡΟΣ' in t:
        return 'second'
    if 'ΤΡΙΤΟΣ' in t:
        return 'third'
    if 'ΤΕΤΑΡΤΟΣ' in t:
        return 'fourth'
    return None


def classify_service(text):
    t = norm_greek(text)
    if 'ΣΥΝΤΟΜΟ' in t:          # ΑΝΑΣΤΑΣΙΜΑΤΑΡΙΟΝ ΣΥΝΤΟΜΟΝ appendix
        return 'syntomon'
    if 'ΟΡΘΡΟΝ' in t or 'ΟΡΘΡΟΣ' in t:
        return 'orthros'
    if 'ΕΣΠΕΡΑΣ' in t:          # ΤΩ ΣΑΒΒΑΤΩ ΕΣΠΕΡΑΣ
        return 'vespers'
    return None


def greek_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    gk = sum(1 for c in letters if 'Ͱ' <= c <= 'Ͽ' or 'ἀ' <= c <= '῿')
    return gk / len(letters)


def font_role(font, size):
    if 'ANNAKEFALEAUC' in font:
        return 'running_header'
    if 'GenesisPt' in font:
        return 'title'
    if 'EcclesiaAthena' in font:
        return 'rubric'
    if 'GFSDidot' in font:
        return 'front_matter'
    if 'ANNA2000' in font:
        return 'initial' if size > 18 else 'page_number'
    if 'SKAlexander' in font:
        return 'lyric'
    return 'other'


def scan_pages(doc):
    pages = []
    for pno in range(len(doc)):
        pg = doc[pno]
        drawings = pg.get_drawings()
        n_fill = n_red = 0
        for dr in drawings:
            if dr['type'] == 'f' and dr['fill'] is not None:
                r, g, b = dr['fill']
                if r > 0.9 and g > 0.9 and b > 0.9:
                    continue          # white background rects
                n_fill += 1
                if r > 0.5 and g < 0.5 and b < 0.5:
                    n_red += 1
        spans = []
        dd = pg.get_text('dict')
        for blk in dd['blocks']:
            if blk['type'] != 0:
                continue
            for ln in blk['lines']:
                for sp in ln['spans']:
                    t = sp['text'].strip()
                    if not t:
                        continue
                    spans.append((sp['bbox'][1], sp['bbox'][0], sp['font'],
                                  sp['size'], t))
        spans.sort(key=lambda s: (round(s[0]), s[1]))
        headers, lyrics, initials = [], [], []
        printed = None
        for y, x, font, size, t in spans:
            role = font_role(font, size)
            if role == 'lyric':
                lyrics.append(t)
            elif role == 'initial':
                initials.append(t)
            elif role == 'page_number':
                m = re.fullmatch(r'\d+', t)
                if m and y < 30 and printed is None:
                    printed = int(t)
                else:
                    headers.append({'role': role, 'text': t, 'y': round(y, 1)})
            elif role in ('running_header', 'title', 'rubric', 'front_matter'):
                headers.append({'role': role, 'text': t, 'y': round(y, 1)})
        # merge header spans on the same visual line
        merged = []
        for h in headers:
            if merged and merged[-1]['role'] == h['role'] and abs(merged[-1]['y'] - h['y']) < 4:
                merged[-1]['text'] += ' ' + h['text']
            else:
                merged.append(dict(h))
        lyric_text = ' '.join(lyrics)
        pages.append({
            'page': pno + 1,
            'printed_page': printed,
            'n_drawings': len(drawings),
            'n_fill': n_fill,
            'n_fill_red': n_red,
            'n_images': len(pg.get_images(full=True)),
            'headers': merged,
            'initials': initials,
            'first_lyric_words': ' '.join(lyrics[:10]),
            'n_lyric_spans': len(lyrics),
            'lyric_greek_ratio': round(greek_ratio(lyric_text), 3),
        })
    return pages


def parse_toc(doc):
    """page 1 TOC: 8 'a-b' printed ranges in canonical mode order (ASCII survives
    the broken ToUnicode)."""
    txt = doc[0].get_text()
    ranges = re.findall(r'(\d+)\s*[-–]\s*(\d+)', txt)
    if len(ranges) != len(MODE_ORDER):
        return None
    return {m: (int(a), int(b)) for m, (a, b) in zip(MODE_ORDER, ranges)}


def derive_sections(pages, toc):
    # printed->pdf offset
    offs = Counter(p['page'] - p['printed_page'] for p in pages
                   if p['printed_page'] is not None)
    offset = offs.most_common(1)[0][0] if offs else None

    # per-page mode/service votes from headers
    for p in pages:
        p_mode = p_srv = None
        for h in p['headers']:
            if h['role'] in ('running_header', 'title'):
                p_mode = p_mode or classify_mode(h['text'])
                p_srv = p_srv or classify_service(h['text'])
        p['_mode'], p['_srv'] = p_mode, p_srv

    # forward/backward fill mode (headers alternate mode-side/service-side)
    n = len(pages)
    fwd = [None] * n
    cur = None
    for i, p in enumerate(pages):
        if p['_mode']:
            cur = p['_mode']
        fwd[i] = cur
    bwd = [None] * n
    cur = None
    for i in range(n - 1, -1, -1):
        if pages[i]['_mode']:
            cur = pages[i]['_mode']
        bwd[i] = cur
    mode_of = []
    for i in range(n):
        if fwd[i] == bwd[i]:
            mode_of.append(fwd[i])
        elif fwd[i] is None:
            mode_of.append(bwd[i])   # front matter before first header -> next mode
        else:
            # between two modes: a mode's closing filler page belongs to the
            # earlier mode only until the next mode's TOC start
            m = None
            if toc and offset is not None:
                pg = i + 1
                for mode in MODE_ORDER:
                    a, b = toc[mode]  # printed; pdf = printed + offset
                    if a + offset <= pg <= b + offset:
                        m = mode
                        break
            mode_of.append(m or bwd[i])
    # page 1 (TOC) is front matter, not a mode page
    if pages[0]['n_fill'] <= 2 and pages[0]['_mode'] is None:
        mode_of[0] = None

    sections = []
    for mode in MODE_ORDER:
        idx = [i + 1 for i in range(n) if mode_of[i] == mode]
        if not idx:
            continue
        sec = {'mode': mode, 'label': MODE_LABEL[mode],
               'pdf_pages': [min(idx), max(idx)],
               'contiguous': idx == list(range(min(idx), max(idx) + 1))}
        if toc and mode in toc:
            a, b = toc[mode]
            sec['toc_printed_pages'] = [a, b]
            if offset is not None:
                sec['toc_pdf_pages'] = [a + offset, b + offset]
                sec['toc_agrees'] = (sec['toc_pdf_pages'] == sec['pdf_pages'])
        # service subranges: forward-fill service inside the mode range
        srv_ranges = []
        cur_srv, start = 'vespers', min(idx)
        for pg in range(min(idx), max(idx) + 1):
            s = pages[pg - 1]['_srv']
            if s and s != cur_srv:
                srv_ranges.append({'service': cur_srv, 'pdf_pages': [start, pg - 1]})
                cur_srv, start = s, pg
        srv_ranges.append({'service': cur_srv, 'pdf_pages': [start, max(idx)]})
        sec['services'] = srv_ranges
        sections.append(sec)
    return sections, offset


def contiguous_ranges(nums):
    out = []
    for x in sorted(nums):
        if out and x == out[-1][1] + 1:
            out[-1][1] = x
        else:
            out.append([x, x])
    return out


def list_audio(raw_dir):
    files = []
    for root, _dirs, fnames in os.walk(raw_dir):
        for f in sorted(fnames):
            if os.path.splitext(f)[1].lower() in AUDIO_EXT:
                files.append(os.path.relpath(os.path.join(root, f), raw_dir))
    return sorted(files)


def _rec_identity(name):
    """'Mode X Anastasimatarion 1 Vespers...' -> (mode, service) or None"""
    low = unicodedata.normalize('NFC', name).lower()
    if 'anastasimatarion' not in low:
        return None
    mode = None
    for key in sorted(AUDIO_MODE, key=len, reverse=True):
        if low.startswith(key + ' '):
            mode = AUDIO_MODE[key]
            break
    if mode is None:
        return None
    if re.search(r'\b1\s+vespers\b', low):
        return mode, 'vespers'
    if re.search(r'\b2\s+orthros\b', low):
        return mode, 'orthros'
    return None


def build_recording_map(audio_files, sections, offset):
    sec_by_mode = {s['mode']: s for s in sections}
    singles, albums = [], {}
    for rel in audio_files:
        parts = rel.split('/')
        base = os.path.splitext(parts[-1])[0]
        parent = parts[-2] if len(parts) > 1 else ''
        ident = _rec_identity(parent)
        if ident:  # track-split album directory named after the recording
            key = '/'.join(parts[:-1])
            albums.setdefault(key, {'ident': ident, 'n': 0})['n'] += 1
            continue
        ident = _rec_identity(base)
        if ident:
            singles.append((rel, ident, None))
    items = singles + [(k + '/', v['ident'], v['n']) for k, v in albums.items()]
    entries = []
    for rel, (mode, service), n_tracks in items:
        sec = sec_by_mode.get(mode)
        entry = {'audio': rel, 'mode': mode, 'service': service}
        if n_tracks is not None:
            entry['kind'] = 'track_split_album'
            entry['n_tracks'] = n_tracks
        else:
            entry['kind'] = 'single_file'
        base = unicodedata.normalize('NFC', os.path.basename(rel.rstrip('/'))).lower()
        if sec:
            srv = {r['service']: r['pdf_pages'] for r in sec['services']}
            pr = srv.get(service)
            entry['pdf_pages'] = pr
            if pr and offset is not None:
                entry['printed_pages'] = [pr[0] - offset, pr[1] - offset]
            conf, notes = 'high', []
            if pr is None:
                conf, notes = 'low', [f'no {service} subrange detected in mode section']
            else:
                if service == 'orthros':
                    conf = 'medium'
                    notes.append('orthros range ends where the syntomon appendix '
                                 'begins; recording may or may not include syntomon')
                notes.append('service boundary from alternating running headers; '
                             'uncertainty about ±1 page at each end')
            if 'plus' in base:
                conf = 'medium'
                notes.append('filename says recording continues past the '
                             'anastasimatarion (e.g. cherubic hymn)')
            entry['confidence'] = conf
            entry['notes'] = notes
        else:
            entry['confidence'] = 'low'
            entry['notes'] = ['mode section not found in book']
        entries.append(entry)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf')
    ap.add_argument('--raw', default=DEFAULT_RAW)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    pdf = args.pdf
    if not pdf:
        for f in os.listdir(args.raw):
            if unicodedata.normalize('NFC', f) == PDF_NAME_NFC:
                pdf = os.path.join(args.raw, f)
                break
    if not pdf or not os.path.exists(pdf):
        sys.exit('anastasimatarion PDF not found')

    doc = fitz.open(pdf)
    pages = scan_pages(doc)
    toc = parse_toc(doc)
    sections, offset = derive_sections(pages, toc)

    non_vector = contiguous_ranges([p['page'] for p in pages if p['n_drawings'] == 0])
    with_images = contiguous_ranges([p['page'] for p in pages if p['n_images'] > 0])
    sparse = contiguous_ranges([p['page'] for p in pages
                                if 0 < p['n_fill'] < 10])
    garbled = contiguous_ranges([p['page'] for p in pages
                                 if p['n_lyric_spans'] >= 5
                                 and p['lyric_greek_ratio'] < 0.5])

    for p in pages:
        p.pop('_mode', None)
        p.pop('_srv', None)

    os.makedirs(args.out, exist_ok=True)
    book_map = {
        'pdf': pdf,
        'n_pages': len(pages),
        'printed_to_pdf_offset': offset,
        'offset_note': (f'pdf_page = printed_page + ({offset}); '
                        f'printed_page = pdf_page - ({offset})')
                       if offset is not None else None,
        'toc_printed_ranges': toc,
        'sections': sections,
        'non_vector_page_ranges': non_vector,
        'pages_with_images': with_images,
        'sparse_notation_ranges': sparse,
        'sparse_note': 'pages with <10 filled paths: mode-end filler/blank pages, still vector',
        'garbled_text_ranges': garbled,
        'garbled_note': 'pages whose lyric text layer has broken ToUnicode (mojibake); '
                        'notation drawings are fine, lyrics unusable as Greek text',
        'pages': pages,
    }
    bm_path = os.path.join(args.out, 'book_map.json')
    with open(bm_path, 'w', encoding='utf-8') as f:
        json.dump(book_map, f, ensure_ascii=False, indent=1)

    # audio inventory: corpus.json if present, else walk raw dir
    audio = None
    if os.path.exists(CORPUS_JSON):
        try:
            cj = json.load(open(CORPUS_JSON, encoding='utf-8'))
            if isinstance(cj, dict):
                audio = cj.get('audio') or cj.get('files') or cj.get('recordings')
            elif isinstance(cj, list):
                audio = cj
        except Exception:
            audio = None
    audio_source = 'corpus.json'
    if not audio:
        audio = list_audio(args.raw)
        audio_source = 'walk raw/vasilikos (corpus.json absent; rsync may still be running)'

    rec_map = build_recording_map(audio, sections, offset)
    found = {(e['mode'], e['service']) for e in rec_map}
    expected_missing = [{'mode': m, 'service': s,
                         'note': 'no matching audio file found yet (rsync in flight?)'}
                        for m in MODE_ORDER for s in ('vespers', 'orthros')
                        if (m, s) not in found]
    rm_path = os.path.join(args.out, 'recording_page_map.json')
    with open(rm_path, 'w', encoding='utf-8') as f:
        json.dump({'audio_source': audio_source,
                   'n_audio_files_seen': len(audio),
                   'recordings': rec_map,
                   'expected_but_unmatched': expected_missing}, f,
                  ensure_ascii=False, indent=1)

    print(f'wrote {bm_path} ({len(pages)} pages)')
    print(f'wrote {rm_path} ({len(rec_map)} mapped, {len(expected_missing)} unmatched)')
    for s in sections:
        print(f"  {s['mode']:14s} pdf {s['pdf_pages']}  toc_agrees={s.get('toc_agrees')}"
              f"  services={[(r['service'], r['pdf_pages']) for r in s['services']]}")
    print('non_vector:', non_vector, 'images:', with_images,
          'sparse:', sparse, 'garbled:', garbled)


if __name__ == '__main__':
    main()
