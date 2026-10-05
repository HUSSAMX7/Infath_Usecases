export type Category = 'computers' | 'mobile_devices' | 'printers_office' | 'tech_accessories';
export type Status = 'queued' | 'processing' | 'classified' | 'needs_review' | 'reviewed' | 'failed';
export interface InvoiceData {invoice_number: string | null; supplier_name: string | null; invoice_date: string | null; subtotal: number | null; vat: number | null; total: number | null; currency: string | null}
export interface LineItem {description: string | null; quantity: number | null; unit_price: number | null; total: number | null}
export interface Warning {code: string; message: string}
export interface Proposal {extracted_data: InvoiceData; items: LineItem[]; classification: Category | null; confidence: number | null; reason: string}
export interface Page {number: number; preview_url: string; status: string; text: string; seconds: number | null; error: string | null; finish_reason: string | null}
export interface Invoice {
  id: string; filename: string; status: Status; stage: string | null; current_page: number | null; page_count: number; size_bytes: number; created_at: string; updated_at: string;
  file_url: string; extracted_data: InvoiceData | null; classification: {key: Category | null; label: string | null; confidence: number | null};
  reviewed_by_user: boolean; reviewed_at: string | null; final_classification: Category | null; warnings: Warning[];
  error: {code: string; message: string; stage: string} | null;
}
export interface Document extends Invoice {
  pages: Page[]; ai_proposal: Proposal | null; final_data: InvoiceData | null; final_items: LineItem[] | null;
  ocr_text: string; ocr_model: string; llm_input: string | null; analysis: {model: string; seconds: number; raw_response: unknown; usage: unknown} | null;
  failure_details: unknown; attempt_seconds: number | null; warnings_acknowledged: boolean;
}
export interface Health {ocr: {available: boolean; state: string; model: string}; openai: {configured: boolean; model: string}; limits: {max_files: number; max_file_mb: number; max_pages: number}}
export interface ReviewPayload {extracted_data: InvoiceData; items: LineItem[]; final_classification: Category | null; acknowledge_warnings: boolean}
export const CATEGORIES: Record<Category, string> = {computers:'أجهزة كمبيوتر',mobile_devices:'جوالات وأجهزة لوحية',printers_office:'طابعات ومعدات مكتبية',tech_accessories:'ملحقات تقنية'};
export const STATUS_LABELS: Record<Status, string> = {queued:'في الانتظار',processing:'قيد المعالجة',classified:'جاهزة للمراجعة',needs_review:'تحتاج مراجعة',reviewed:'تم الاعتماد',failed:'توقفت المعالجة'};
