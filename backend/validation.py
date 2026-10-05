from decimal import Decimal
from .models import InvoiceData, LineItem, WarningItem

FIELD_NAMES = {
    'invoice_number': 'رقم الفاتورة', 'supplier_name': 'اسم المورد',
    'invoice_date': 'تاريخ الفاتورة', 'subtotal': 'المجموع الفرعي',
    'vat': 'مبلغ الضريبة', 'total': 'الإجمالي', 'currency': 'العملة',
}


def validate_invoice(data: InvoiceData, items: list[LineItem]) -> list[WarningItem]:
    warnings = []
    for key, label in FIELD_NAMES.items():
        value = getattr(data, key)
        if value is None or (isinstance(value, str) and not value.strip()):
            warnings.append(WarningItem(code=f'missing_{key}', message=f'{label} غير متوفر؛ تحقّق من المستند.'))
    money = lambda value: Decimal(str(value))
    tolerance = Decimal('0.01')
    if data.subtotal is not None and data.vat is not None and data.total is not None:
        if abs(money(data.subtotal) + money(data.vat) - money(data.total)) > tolerance:
            warnings.append(WarningItem(code='total_mismatch', message='المجموع الفرعي والضريبة لا يطابقان الإجمالي؛ تحقّق من الخصومات والرسوم.'))
    if items and all(item.total is not None for item in items) and data.subtotal is not None:
        if abs(sum((money(item.total) for item in items), Decimal(0)) - money(data.subtotal)) > tolerance:
            warnings.append(WarningItem(code='items_mismatch', message='مجموع البنود يختلف عن المجموع الفرعي؛ تحقّق من القراءة والخصومات.'))
    for index, item in enumerate(items, 1):
        if any(getattr(item, key) is None for key in ('description', 'quantity', 'unit_price', 'total')):
            warnings.append(WarningItem(code=f'item_{index}_missing', message=f'البند {index} يحتوي بيانات ناقصة.'))
        if all(getattr(item, key) is not None for key in ('quantity', 'unit_price', 'total')):
            if abs(money(item.quantity) * money(item.unit_price) - money(item.total)) > tolerance:
                warnings.append(WarningItem(code=f'item_{index}_mismatch', message=f'الكمية وسعر الوحدة لا يطابقان إجمالي البند {index}؛ تحقّق من الخصومات.'))
    if not items:
        warnings.append(WarningItem(code='missing_items', message='لم تُستخرج بنود للفاتورة.'))
    return warnings
