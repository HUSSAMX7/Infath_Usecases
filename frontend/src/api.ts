import type {Document, Health, Invoice, ReviewPayload, Warning} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response:Response;
  try {response = await fetch('/api' + path, init);}
  catch {throw new Error('تعذّر الاتصال بالخدمة المحلية. تأكد من تشغيل التطبيق.');}
  const body = await response.json().catch(()=>null);
  if (!body) throw new Error('تعذّر إكمال الطلب لدى الخدمة المحلية. راجع سجل التطبيق ثم أعد المحاولة.');
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'تعذّر إكمال الطلب. تحقّق من البيانات والاتصال.');
  }
  return body as T;
}
const json = (body: unknown): RequestInit => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const api = {
  health: () => request<Health>('/health'),
  list: () => request<{invoices:Invoice[]}>('/invoices'),
  get: (id:string) => request<Document>(`/invoices/${id}`),
  upload: (files:File[]) => {const data = new FormData(); files.forEach(file=>data.append('files',file)); return request<{invoices:Invoice[];errors:{filename:string;message:string}[]}>('/invoices',{method:'POST',body:data});},
  validate: (id:string, payload:ReviewPayload) => request<{warnings:Warning[]}>(`/invoices/${id}/review/validate`,json(payload)),
  review: (id:string, payload:ReviewPayload) => request<Document>(`/invoices/${id}/review`,json(payload)),
  retry: (id:string) => request<Document>(`/invoices/${id}/retry`,json({})),
};
