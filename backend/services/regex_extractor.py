"""Conservative extraction from OCR text. No model, network, or invoice templates.

Rules select explicit labels and unique values. Conflicting/unsupported values stay
null. Tables are parsed structurally, never with regex over HTML markup.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from dataclasses import dataclass
import hashlib
import json
import re
import time
import unicodedata

from ..models import InvoiceData, LineItem, Proposal


DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
ARABIC = str.maketrans('أإآىة', 'ااايه')
EXTRACTOR_VERSION = 'Regex + table parser v2'


def clean(text: str) -> str:
    text = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
    return re.sub(r'\s+', ' ', text.translate(DIGITS).replace('٪', '%').replace('**', '').replace('__', '')).strip(' #\t')


def folded(text: str) -> str:
    return re.sub(r'[\u064b-\u065f\u0670]', '', clean(text)).translate(ARABIC).lower()


LABELS = {
    'invoice_number': r'رقم\s*الفاتوره|invoice\s*(?:number|no\.?|#)|فاتوره\s*رقم',
    'supplier_name': r'اسم\s*(?:المورد|البائع)|المورد|البائع|supplier(?:\s*name)?|vendor(?:\s*name)?|seller(?:\s*name)?|issued\s*by',
    'invoice_date': r'تاريخ\s*(?:الفاتوره|الاصدار)|invoice\s*date|issue\s*date|التاريخ|date',
    'subtotal': r'المجموع\s*الفرعي|الاجمالي\s*(?:الفرعي|قبل\s*الضريبه)|subtotal|sub\s*total|net\s*total',
    'vat': r'ض(?:ريبه|ربيه|ريبيه)\s*القيمه\s*(?:المضافه|اضافه)|مبلغ\s*الضريبه|اجمالي\s*الضريبه|الضريبه|total\s*tax|tax\s*amount|vat(?:\s*amount)?|tax',
    'total': r'الاجمالي\s*النهائي|المجموع\s*الكلي|المبلغ\s*الاجمالي|الاجمالي|grand\s*total|invoice\s*total|total\s*amount|total',
    'currency': r'العمله|currency',
    # Consume unrelated labels so a date/amount cannot absorb their values.
    'other': r'due\s*date|delivery\s*date|payment\s*date|تاريخ\s*(?:الاستحقاق|التسليم|الدفع)|customer(?:\s*name)?|اسم\s*العميل|العميل|الرقم\s*الضريبي|tax\s*(?:id|number)|vat\s*(?:id|number)',
}
LABEL_RE = re.compile(r'(?<!\w)(?:' + '|'.join(f'(?P<{key}>{pattern})' for key, pattern in sorted(LABELS.items(), key=lambda item: item[0] != 'other')) + r')(?!\w)', re.I)
NUMBER_RE = re.compile(r'(?<![\w.,/])[-+]?\d+(?:[.,]\d+)*(?![\w.,/])')
CURRENCY_PATTERNS = {
    'SAR': r'\bsar\b|ريال\s*سعودي|ر\s*\.\s*س\b',
    'USD': r'\busd\b|دولار\s*امريكي|us\s*\$',
    'EUR': r'\beur\b|يورو|€', 'GBP': r'\bgbp\b|جنيه\s*استرليني|£',
    'AED': r'\baed\b|درهم\s*اماراتي', 'QAR': r'\bqar\b|ريال\s*قطري',
    'KWD': r'\bkwd\b|دينار\s*كويتي', 'BHD': r'\bbhd\b|دينار\s*بحريني',
    'OMR': r'\bomr\b|ريال\s*عماني',
}

# Approximation is restricted to complete, isolated labels, never arbitrary prose
# or numbers. A single insertion/deletion/substitution/transposition is allowed.
CANONICAL_LABELS = {
    'invoice_number': ['رقم الفاتورة', 'فاتورة رقم', 'invoice number', 'invoice no'],
    'supplier_name': ['اسم المورد', 'اسم البائع', 'supplier name', 'vendor name', 'seller name', 'issued by'],
    'invoice_date': ['تاريخ الفاتورة', 'تاريخ الاصدار', 'invoice date', 'issue date', 'التاريخ'],
    'subtotal': ['المجموع الفرعي', 'الاجمالي الفرعي', 'الاجمالي قبل الضريبة', 'subtotal', 'sub total', 'net total'],
    'vat': ['ضريبة القيمة المضافة', 'مبلغ الضريبة', 'اجمالي الضريبة', 'الضريبة', 'total tax', 'tax amount', 'vat amount'],
    'total': ['الاجمالي النهائي', 'المجموع الكلي', 'المبلغ الاجمالي', 'الاجمالي', 'grand total', 'invoice total', 'total amount'],
    'currency': ['العملة', 'currency'],
    'other': ['اسم العميل', 'customer name', 'due date', 'delivery date', 'payment date', 'الرقم الضريبي', 'tax number', 'vat number'],
}
NORMALIZED_LABELS = [(folded(name), field) for field, names in CANONICAL_LABELS.items() for name in names]


def one_edit(a: str, b: str) -> bool:
    """Bounded edit distance (including one adjacent transposition)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        return len(differences) == 1 or (len(differences) == 2 and differences[1] == differences[0] + 1
                                       and a[differences[0]] == b[differences[1]] and a[differences[1]] == b[differences[0]])
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for index, (x, y) in enumerate(zip(shorter, longer)):
        if x != y:
            return shorter[index:] == longer[index + 1:]
    return True


@dataclass(frozen=True)
class Label:
    field: str
    match: str
    text: str


def identify_label(value: str) -> Label | None:
    if len(value) > 160:
        return None
    normalized = folded(value).strip(' :：=.-')
    # VAT percentage is part of a label, not its monetary value.
    normalized = re.sub(r'\s*\(?\d+(?:[.,]\d+)?\s*%\)?\s*$', '', normalized).strip()
    exact = LABEL_RE.fullmatch(normalized)
    if exact:
        return Label(exact.lastgroup, 'exact', value)
    if len(normalized.replace(' ', '')) < 8 or re.search(r'[\d:;=]', normalized):
        return None
    fields = {field for name, field in NORMALIZED_LABELS if one_edit(normalized, name)}
    return Label(next(iter(fields)), 'fuzzy', value) if len(fields) == 1 else None


def parse_field(field: str, value: str):
    value = clean(value).strip(' :：=')
    if field == 'invoice_date':
        return invoice_date(value)
    if field in ('subtotal', 'vat', 'total'):
        return amount(value)
    if field == 'invoice_number':
        return value if re.fullmatch(r'[\w][\w./-]{0,99}', value) else None
    if field == 'supplier_name':
        return value if value and len(value) <= 160 and not re.search(r'\b(?:customer|bill\s*to)\b|اسم\s*العميل', folded(value)) else None
    return None


def mapped_matches(line: str):
    matching, offsets = '', []
    for offset, character in enumerate(line):
        piece = re.sub(r'[\u064b-\u065f\u0670]', '', character).translate(ARABIC).lower()
        matching += piece
        offsets.extend([offset] * len(piece))
    return [(m.lastgroup, offsets[m.start()], offsets[m.end() - 1] + 1) for m in LABEL_RE.finditer(matching)]


def page_boundary(line: str) -> bool:
    return bool(re.fullmatch(r'---\s*PAGE\s+\d+\s*---', line, re.I))


def line_pairs(lines: list[str]):
    """Yield labels/values with evidence, preserving the OCR's original values."""
    for index, line in enumerate(lines):
        if page_boundary(line):
            continue
        # An isolated label can have a value on the following line. Never cross
        # another label or page boundary, or borrow the preceding field's value.
        label = identify_label(line)
        if label:
            following = lines[index + 1] if index + 1 < len(lines) else ''
            if following and not page_boundary(following) and not identify_label(following) and not mapped_matches(following):
                yield label, following, 'following_line', line + '\n' + following
            elif label.field not in ('other', 'currency'):
                yield label, '', 'isolated_label', line
            continue
        # Approximation and reversed orientation are only allowed at explicit
        # key/value delimiters. This prevents matching a label inside terms.
        parts = re.split(r'\s*[:：=]\s*', line, maxsplit=1)
        if len(parts) == 2:
            left, right = parts
            left_label, right_label = identify_label(left), identify_label(right)
            if right_label and not left_label:
                yield right_label, left, 'value_before_label', line
                continue
            if left_label and left_label.match == 'fuzzy':
                yield left_label, right, 'label_before_value', line
                continue
        matches = mapped_matches(line)
        if not matches or line[:matches[0][1]].strip(' -•'):
            continue
        for position, (field, start, end) in enumerate(matches):
            stop = matches[position + 1][1] if position + 1 < len(matches) else len(line)
            value = line[end:stop].strip(' :：=')
            yield Label(field, 'exact', line[start:end]), value, 'label_before_value', line


def numeric(value: str) -> float | None:
    """Accept an entire numeric value; reject ambiguous grouping and junk."""
    value = clean(value)
    negative = value.startswith('(') and value.endswith(')')
    if negative:
        value = value[1:-1].strip()
    if not re.fullmatch(r'[-+]?\d+(?:[.,]\d+)*', value):
        return None
    if ',' in value and '.' in value:
        decimal = ',' if value.rfind(',') > value.rfind('.') else '.'
        thousands = '.' if decimal == ',' else ','
        integer, fraction = value.rsplit(decimal, 1)
        if not re.fullmatch(r'[-+]?\d{1,3}(?:' + re.escape(thousands) + r'\d{3})+', integer) or not 1 <= len(fraction) <= 2:
            return None
        value = integer.replace(thousands, '') + '.' + fraction
    elif ',' in value:
        if re.fullmatch(r'[-+]?\d{1,3}(?:,\d{3})+', value):
            value = value.replace(',', '')
        elif re.fullmatch(r'[-+]?\d+,\d{1,2}', value):
            value = value.replace(',', '.')
        else:
            return None
    elif value.count('.') > 1 or ('.' in value and len(value.rsplit('.', 1)[1]) > 2):
        return None
    try:
        amount = Decimal(value)
        result = float(-amount if negative else amount)
        return result if amount.is_finite() and abs(amount) <= Decimal('1e15') else None
    except (InvalidOperation, ValueError):
        return None


def amount(value: str) -> float | None:
    matches = [m for m in NUMBER_RE.finditer(clean(value)) if not re.match(r'\s*%', clean(value)[m.end():])]
    if len(matches) != 1:
        return None
    match = matches[0]
    raw = match.group()
    if re.search(r'\(\s*$', clean(value)[:match.start()]) and re.match(r'\s*\)', clean(value)[match.end():]):
        raw = '(' + raw + ')'
    return numeric(raw)


def invoice_date(value: str) -> str | None:
    matches = re.findall(r'(?<!\d)(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})(?!\d)', clean(value))
    if len(matches) != 1:
        return None
    a, b, c = matches[0]
    try:
        if len(a) == 4:
            return date(int(a), int(b), int(c)).isoformat()
        if len(c) != 4:
            return None
        if int(a) > 12:
            return date(int(c), int(b), int(a)).isoformat()
        if int(b) > 12:
            return date(int(c), int(a), int(b)).isoformat()
        if a == b:
            return date(int(c), int(b), int(a)).isoformat()
    except ValueError:
        pass
    return None  # e.g. 02/06/2024 has two possible interpretations.


class OcrHtml(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.cell_attributes = {}
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        if tag == 'table':
            self.depth += 1
            if self.depth == 1:
                self.table = {'rows': [], 'raw_rows': [], 'row_meta': [], 'unsupported': False}
            else:
                self.table['unsupported'] = True
        elif self.depth == 1 and tag == 'tr':
            self.row = []
        elif self.depth == 1 and tag in ('td', 'th'):
            self.cell_attributes = dict(attrs)
            self.cell = []
        elif tag in ('br', 'p', 'div', 'h1', 'h2', 'h3', 'li'):
            if self.cell is not None:
                self.cell.append(' ')
            elif not self.depth:
                # A <br> inside a paragraph continues that name/value. Block
                # boundaries still separate unrelated fields and addresses.
                self.text.append(' ' if tag == 'br' else '\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if self.depth == 1 and tag in ('td', 'th') and self.cell is not None and self.row is not None:
            attributes = self.cell_attributes
            spans = {}
            for key in ('rowspan', 'colspan'):
                try:
                    spans[key] = int(attributes.get(key, '1'))
                    if not 1 <= spans[key] <= 100:
                        raise ValueError()
                except (ValueError, TypeError):
                    self.table['unsupported'] = True
                    spans[key] = 1
            self.row.append({'text': clean(''.join(self.cell)), **spans})
            self.cell = None
        elif self.depth == 1 and tag == 'tr' and self.row is not None:
            if self.cell is not None:
                self.table['unsupported'] = True
            self.table['raw_rows'].append(self.row)
            self.row = None
        elif tag == 'table' and self.depth:
            self.depth -= 1
            if not self.depth:
                if self.row is not None or self.cell is not None:
                    self.table['unsupported'] = True
                expand_grid(self.table)
                self.tables.append(self.table)
                self.table = self.row = self.cell = None
        elif not self.depth and tag in ('p', 'div', 'h1', 'h2', 'h3', 'li'):
            self.text.append('\n')

    def handle_data(self, data):
        if self.skip:
            return
        if self.depth > 1:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif not self.depth:
            self.text.append(data)


def expand_grid(table):
    """Resolve HTML spans into column positions, retaining physical-cell origins.

    Empty spanning cells in summaries must reserve columns. Text spanning two
    different item columns is not assigned to both fields as a guessed value.
    """
    active = {}
    for raw in table['raw_rows']:
        cells = {column: record for column, (record, remaining) in active.items()}
        next_active = {column: (record, remaining - 1) for column, (record, remaining) in active.items() if remaining > 1}
        cursor = 0
        for origin, record in enumerate(raw):
            width = record['colspan']
            while any(column in cells for column in range(cursor, cursor + width)):
                cursor += 1
                if cursor > 100:
                    table['unsupported'] = True
                    break
            if cursor + width > 100:
                table['unsupported'] = True
                break
            for column in range(cursor, cursor + width):
                cells[column] = record
                if record['rowspan'] > 1:
                    next_active[column] = (record, record['rowspan'] - 1)
            cursor += width
        width = max(cells, default=-1) + 1
        table['rows'].append([cells.get(column, {}).get('text', '') for column in range(width)])
        table['row_meta'].append({'cells': cells, 'physical': raw})
        active = next_active


TABLE_HEADERS = {
    'description': r'^(?:الصنف|الوصف|البيان|اسم\s*الصنف|description|item(?:\s*description)?|product|service)(?:\s|$)',
    'quantity': r'^(?:الكميه|العدد|quantity|qty\.?)$',
    'unit_price': r'^(?:سعر\s*الوحده|سعر|unit\s*price|price|rate)(?:\s|$)',
    'total': r'^(?:الاجمالي|المجموع|القيمه|اجمالي\s*البند|line\s*total|total|amount)(?:\s|$)',
}


def column_map(row):
    columns = {}
    for index, cell in enumerate(row):
        header = folded(re.sub(r'\([^)]*\)', '', cell))
        for field, pattern in TABLE_HEADERS.items():
            if re.search(pattern, header):
                if field in columns:
                    return {}  # two total/price columns cannot be resolved by position.
                columns[field] = index
    return columns if 'description' in columns and len(columns) >= 2 else {}


def markdown_tables(text):
    tables, rows = [], []
    for line in text.splitlines() + ['']:
        if '|' in line and line.strip().startswith('|'):
            cells = [clean(c.replace('\\|', '|')) for c in re.split(r'(?<!\\)\|', line.strip().strip('|'))]
            if all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells):
                continue
            rows.append(cells)
        elif rows:
            tables.append({'rows': rows, 'unsupported': False})
            rows = []
    return tables


def row_pairs(row, meta=None):
    # Use physical cells for field labels; colspan expansion would otherwise
    # repeat the same label/value and corrupt pairing or provenance.
    cells = [cell['text'] for cell in meta['physical']] if meta else row
    labels = [(index, identify_label(cell)) for index, cell in enumerate(cells)]
    labels = [(index, label) for index, label in labels if label]
    for position, (index, label) in enumerate(labels):
        if label.field in ('other', 'currency'):
            continue
        if len(labels) == 1:
            parts = [cell for other, cell in enumerate(cells) if other != index and cell]
        elif labels[0][0] == 0:
            stop = labels[position + 1][0] if position + 1 < len(labels) else len(cells)
            parts = cells[index + 1:stop]
        else:
            start = labels[position - 1][0] + 1 if position else 0
            parts = cells[start:index]
        value = ' '.join(parts)
        if parse_field(label.field, value) is not None:
            yield label, value, 'table_cells', ' | '.join(cells)
        else:
            # More than one possible numeric value is an ambiguity, not a
            # license to select whichever happens to be closest to the label.
            valid_parts = [part for part in parts if parse_field(label.field, part) is not None]
            if valid_parts:
                for part in valid_parts:
                    yield label, part, 'table_cells', ' | '.join(cells)
                for part in parts:
                    if re.search(r'\d', part) and parse_field(label.field, part) is None:
                        yield label, part, 'table_cells', ' | '.join(cells)
            else:
                yield label, value, 'table_cells', ' | '.join(cells)


class RegexExtractor:
    def classify_invoice(self, invoice_text: str) -> dict:
        started = time.perf_counter()
        parser = OcrHtml()
        parser.feed(invoice_text)
        parser.close()
        if parser.table is not None:
            parser.table['unsupported'] = True
            expand_grid(parser.table)
            parser.tables.append(parser.table)
        text = ''.join(parser.text)
        lines = [clean(line) for line in text.splitlines() if clean(line) and not line.strip().startswith('|')]
        tables = parser.tables + markdown_tables(text)
        candidates = {key: [] for key in InvoiceData.model_fields}
        fuzzy_labels = set()

        def add_pairs(pairs):
            for label, raw, orientation, source in pairs:
                if label.field not in candidates or label.field == 'currency':
                    continue
                candidates[label.field].append({'value': parse_field(label.field, raw), 'rule': orientation,
                                               'match': label.match, 'label': label.text, 'text': source})
                if label.match == 'fuzzy':
                    fuzzy_labels.add(label.text)

        add_pairs(line_pairs(lines))
        summary_rows = set()
        for number, table in enumerate(tables):
            if table['unsupported']:
                continue
            for index, row in enumerate(table['rows']):
                if column_map(row):
                    continue
                meta = table.get('row_meta', [])[index] if table.get('row_meta') else None
                pairs = list(row_pairs(row, meta))
                if pairs:
                    summary_rows.add((number, index))
                    add_pairs(pairs)
        if not candidates['invoice_number']:
            for match in re.finditer(r'(?<!\w)INV[-/]\d[\w-]*(?!\w)', text.translate(DIGITS), re.I):
                candidates['invoice_number'].append({'value': match.group(), 'rule': 'unique_INV_identifier', 'text': match.group()})
        if not candidates['supplier_name']:
            headings = []
            for line in lines:
                if page_boundary(line) or line.startswith('![image]'):
                    continue
                if mapped_matches(line) or re.search(r'فاتوره|invoice', folded(line)):
                    break
                if re.search(r'شركه|مؤسسه|للمقاولات|للتجاره|\b(?:company|llc|ltd|trading)\b', folded(line)):
                    headings.append(line)
            # Duplicate logo/headings are common. Prefer a longer heading only
            # when it contains the shorter heading's complete word sequence.
            # Distinct company headings remain conflicting candidates.
            for line in headings:
                name = folded(line)
                if any(name != folded(other) and (' ' + name + ' ') in (' ' + folded(other) + ' ') for other in headings):
                    continue
                candidates['supplier_name'].append({'value': line, 'rule': 'issuer_heading_before_invoice', 'text': line})
        entire = folded(text + '\n' + '\n'.join(' '.join(row) for table in tables for row in table['rows']))
        for code, pattern in CURRENCY_PATTERNS.items():
            match = re.search(pattern, entire)
            if match:
                candidates['currency'].append({'value': code, 'rule': 'explicit_currency', 'text': match.group()})
        if re.search(r'السعوديه|saudi\s*arabia', entire) and re.search(r'(?<!\w)(?:ريالا?|riyals?|rials?)(?!\w)', entire) and not re.search(r'ريالا?\s*(?:قطري|عماني)', entire):
            candidates['currency'].append({'value': 'SAR', 'rule': 'riyal_with_explicit_Saudi_context', 'text': 'ريال + السعودية'})
        values, evidence = {}, {}
        for field, matches in candidates.items():
            unique = {str(m['value']) for m in matches if m['value'] is not None}
            resolved = len(unique) == 1 and all(m['value'] is not None for m in matches)
            values[field] = matches[0]['value'] if resolved else None
            evidence[field] = {'status': 'matched' if resolved else 'missing' if not matches else 'ambiguous' if len(unique) > 1 else 'unrecognized', 'candidates': matches}
        items, table_notes = [], []
        for number, table in enumerate(tables, 1):
            columns = {}
            if table['unsupported']:
                table_notes.append(f'الجدول {number}: بنية غير مكتملة أو متداخلة أو دمج غير صالح؛ راجع البنود يدويًا.')
                continue
            for index, row in enumerate(table['rows']):
                header = column_map(row)
                if header:
                    columns = header
                    continue
                if not columns or not any(row):
                    continue
                if (number - 1, index) in summary_rows:
                    continue
                if max(columns.values()) >= len(row):
                    table_notes.append(f'الجدول {number}: صف غير مكتمل؛ راجع البنود يدويًا.')
                    continue
                description = row[columns['description']]
                if not description:
                    table_notes.append(f'الجدول {number}: صف بلا وصف؛ راجع البنود يدويًا.')
                    continue
                if identify_label(description):
                    continue  # summary/footer, not a purchased item.
                meta = table.get('row_meta', [])[index] if table.get('row_meta') else None
                if meta and any(meta['cells'].get(column, {}).get('colspan', 1) > 1 and meta['cells'].get(column, {}).get('text') for column in columns.values()):
                    table_notes.append(f'الجدول {number}: صف يدمج أكثر من عمود للبند؛ راجع هذا الصف يدويًا.')
                    continue
                item = {'description': description}
                for field in ('quantity', 'unit_price', 'total'):
                    item[field] = amount(row[columns[field]]) if field in columns else None
                items.append(LineItem.model_validate(item))
            if not columns and any(any(row) for row in table['rows']) and not any(table_id == number - 1 for table_id, _ in summary_rows):
                table_notes.append(f'الجدول {number}: عناوين أعمدة غير معروفة؛ راجع البنود يدويًا.')
        proposal = Proposal(extracted_data=InvoiceData.model_validate(values), items=items, classification=None, confidence=None,
                            reason='القواعد تستخرج الحقول والبنود فقط؛ اختر تصنيف الفاتورة أثناء المراجعة.')
        warnings = [{'code': 'regex_table_attention', 'message': 'بعض الجداول أو الصفوف لم تُحسم بالقواعد؛ قارن البنود بقراءة OCR قبل الاعتماد.'}] if table_notes else []
        if fuzzy_labels:
            warnings.append({'code': 'regex_fuzzy_label', 'message': 'استُخدمت مطابقة تقريبية لعنوان حقل؛ راجع القيم وعناوينها في المستند: ' + '، '.join(sorted(fuzzy_labels))})
        result = {'proposal': proposal.model_dump(mode='json'), 'method': 'regex', 'model': EXTRACTOR_VERSION,
                'seconds': time.perf_counter() - started, 'usage': None, 'extraction_warnings': warnings,
                'raw_response': {'fields': evidence, 'tables_seen': len(tables), 'items_extracted': len(items), 'table_notes': table_notes,
                                 'pipeline': ['normalize', 'parse_document_structure', 'match_labels', 'pair_values', 'resolve_conflicts', 'parse_items'],
                                 'fuzzy_labels': sorted(fuzzy_labels)}}
        # Stable provenance identifies exactly which result a human reviewed.
        result['revision'] = hashlib.sha256(json.dumps({'input': invoice_text, 'model': EXTRACTOR_VERSION,
                                                       'proposal': result['proposal'], 'evidence': result['raw_response']},
                                                      ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return result
