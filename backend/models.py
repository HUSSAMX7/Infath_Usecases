from enum import Enum
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Category(str, Enum):
    computers = 'computers'
    mobile_devices = 'mobile_devices'
    printers_office = 'printers_office'
    tech_accessories = 'tech_accessories'


LABELS = {
    Category.computers: 'أجهزة كمبيوتر',
    Category.mobile_devices: 'جوالات وأجهزة لوحية',
    Category.printers_office: 'طابعات ومعدات مكتبية',
    Category.tech_accessories: 'ملحقات تقنية',
}


class InvoiceData(StrictModel):
    invoice_number: str | None
    supplier_name: str | None
    invoice_date: date | None
    subtotal: float | None
    vat: float | None
    total: float | None
    currency: str | None


class LineItem(StrictModel):
    description: str | None
    quantity: float | None
    unit_price: float | None
    total: float | None


class Proposal(StrictModel):
    extracted_data: InvoiceData
    items: list[LineItem]
    classification: Category | None
    confidence: Annotated[float, Field(ge=0, le=1)] | None
    reason: str

    @model_validator(mode='after')
    def consistent_confidence(self):
        if self.classification is not None and self.confidence is None:
            raise ValueError('A proposed category requires confidence.')
        if self.classification is None and self.confidence is not None:
            raise ValueError('An out-of-scope invoice must have null confidence.')
        return self


class ReviewRequest(StrictModel):
    extracted_data: InvoiceData
    items: list[LineItem]
    final_classification: Category | None
    acknowledge_warnings: bool = False
    source: Literal['original', 'regex'] = 'original'
    regex_revision: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None


class WarningItem(StrictModel):
    code: str
    message: str
