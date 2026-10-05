import { useEffect, useState } from 'react';
import { Check, CheckCheck, Plus, ShieldCheck, Trash2, TriangleAlert } from 'lucide-react';
import { api } from '../api';
import { CATEGORIES } from '../types';
import type { Category, Document, InvoiceData, LineItem, ReviewPayload, Warning } from '../types';

const fields: {key:keyof InvoiceData;label:string;type:string}[] = [
  {key:'supplier_name',label:'اسم المورد',type:'text'}, {key:'invoice_number',label:'رقم الفاتورة',type:'text'},
  {key:'invoice_date',label:'تاريخ الفاتورة',type:'date'}, {key:'currency',label:'العملة',type:'text'},
  {key:'subtotal',label:'المجموع الفرعي',type:'number'}, {key:'vat',label:'مبلغ الضريبة',type:'number'}, {key:'total',label:'الإجمالي النهائي',type:'number'},
];
const numberValue = (value:string) => value === '' || !Number.isFinite(Number(value)) ? null : Number(value);

export function ReviewForm({document, onSaved}:{document:Document;onSaved:(doc:Document)=>void}) {
  const proposal = document.ai_proposal!;
  const [data,setData] = useState<InvoiceData>({...document.final_data || proposal.extracted_data});
  const [items,setItems] = useState<LineItem[]>(structuredClone(document.final_items || proposal.items));
  const [category,setCategory] = useState<Category|null>(document.reviewed_by_user ? document.final_classification : proposal.classification);
  const [warnings,setWarnings] = useState<Warning[]>(document.warnings);
  const [ack,setAck] = useState(false);
  const [validated,setValidated] = useState(false);
  const [saving,setSaving] = useState(false);
  const [error,setError] = useState('');
  const [saved,setSaved] = useState(false);
  useEffect(()=>{
    let cancelled=false;
    setValidated(false); setAck(false); setSaved(false);
    const timer=setTimeout(()=>{
      api.validate(document.id,{extracted_data:data,items,final_classification:category,acknowledge_warnings:false})
        .then(result=>{if(!cancelled){setWarnings(result.warnings);setValidated(true);setError('');}})
        .catch(e=>{if(!cancelled)setError(e.message);});
    },350);
    return ()=>{cancelled=true;clearTimeout(timer);};
  },[document.id,data,items,category]);
  const updateItem=(index:number,key:keyof LineItem,value:string)=>setItems(items.map((item,i)=>i===index?{...item,[key]:key==='description'?(value||null):numberValue(value)}:item));
  async function save(){
    setSaving(true);setError('');
    const payload:ReviewPayload={extracted_data:data,items,final_classification:category,acknowledge_warnings:ack};
    try{const result=await api.review(document.id,payload);onSaved(result);setSaved(true);}
    catch(e){setError(e instanceof Error?e.message:'تعذّر الحفظ.');}
    finally{setSaving(false);}
  }
  return <section className="review-section">
    <div className="section-heading"><div><span className="eyebrow">المراجعة البشرية</span><h2>راجع، ثم اعتمد</h2><p>صحّح فقط ما أنت متأكد منه. قراءة النموذج الأصلية محفوظة دائمًا.</p></div><span className="quiet-badge"><ShieldCheck size={16}/> القرار الأخير لك</span></div>
    <div className="review-grid">
      <div className="panel fields-panel"><div className="panel-heading"><h3>بيانات الفاتورة</h3><span>حقول قابلة للتعديل</span></div>
        <div className="form-grid">{fields.map(field=>{
          const changed=String(data[field.key]??'')!==String(proposal.extracted_data[field.key]??'');
          return <label className={field.key==='supplier_name'?'wide':''} key={field.key}>{field.label}
            <input aria-label={field.label} type={field.type} step={field.type==='number'?'any':undefined} value={data[field.key]??''} placeholder="غير مقروء" dir={field.key==='supplier_name'?'auto':'ltr'}
              onChange={e=>setData({...data,[field.key]:field.type==='number'?numberValue(e.target.value):(e.target.value||null)})}/>
            {changed&&<small className="changed">قراءة النموذج: {proposal.extracted_data[field.key]??'غير متوفر'}</small>}
          </label>;
        })}</div>
      </div>
      <div className="panel classification-panel"><div className="panel-heading"><h3>تصنيف الفاتورة</h3><span>اقتراح قابل للمراجعة</span></div>
        <div className="ai-suggestion"><div className="suggestion-icon"><ShieldCheck size={23}/></div><div><small>اقتراح النموذج الأصلي</small><strong>{proposal.classification?CATEGORIES[proposal.classification]:'خارج نطاق التصنيفات'}</strong></div>
          {proposal.confidence!==null&&<div className="confidence"><strong>{Math.round(proposal.confidence*100)}<small>%</small></strong><span>تقدير الثقة</span></div>}
        </div>
        <p className="reason">{proposal.reason}</p>
        <label className="category-label">التصنيف النهائي<select aria-label="التصنيف النهائي" value={category??''} onChange={e=>setCategory((e.target.value||null) as Category|null)}><option value="">خارج نطاق التصنيفات — بلا تصنيف</option>{Object.entries(CATEGORIES).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
        <div className="category-chips">{Object.entries(CATEGORIES).map(([key,label])=><button type="button" key={key} className={category===key?'chosen':''} onClick={()=>setCategory(key as Category)}>{category===key&&<Check size={13}/>} {label}</button>)}</div>
        <p className="hint">الثقة تقدير من النموذج، وليست نسبة دقة مقاسة. لا يُعتمد التصنيف تلقائيًا.</p>
      </div>
    </div>
    <div className="panel items-panel"><div className="panel-heading"><h3>بنود الفاتورة <span className="count">{items.length}</span></h3><button className="text-button" type="button" onClick={()=>setItems([...items,{description:null,quantity:null,unit_price:null,total:null}])}><Plus size={15}/> إضافة بند</button></div>
      <div className="table-scroll"><table className="items-table"><thead><tr><th>الصنف / الخدمة</th><th>الكمية</th><th>سعر الوحدة</th><th>الإجمالي</th><th><span className="sr-only">حذف</span></th></tr></thead><tbody>{items.map((item,index)=><tr key={index}>{(['description','quantity','unit_price','total'] as const).map(key=><td key={key}><input aria-label={`${key==='description'?'وصف':key==='quantity'?'كمية':key==='unit_price'?'سعر':'إجمالي'} البند ${index+1}`} type={key==='description'?'text':'number'} step="any" value={item[key]??''} placeholder="—" dir={key==='description'?'auto':'ltr'} onChange={e=>updateItem(index,key,e.target.value)}/></td>)}<td><button className="icon-button" aria-label={`حذف البند ${index+1}`} onClick={()=>setItems(items.filter((_,i)=>i!==index))}><Trash2 size={15}/></button></td></tr>)}</tbody></table></div>
      {!items.length&&<p className="hint empty-items">لم تُستخرج بنود. يمكنك إضافتها إذا كانت واضحة في المستند.</p>}
    </div>
    {warnings.length>0&&<div className="warning-box"><div className="warning-title"><TriangleAlert size={19}/><strong>تنبيهات تحتاج نظرة منك</strong></div><ul>{warnings.map(w=><li key={w.code}>{w.message}</li>)}</ul><label className="acknowledge"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/> راجعت التنبيهات وأقرّ باعتماد النتيجة بهذه البيانات.</label></div>}
    {error&&<p className="error-inline" role="alert">{error}</p>}
    <div className="approval-bar"><div><ShieldCheck size={20}/><span>{document.reviewed_by_user?'المراجعة محفوظة؛ يمكنك حفظ تصحيح جديد.':'حفظ البيانات النهائية مع الاحتفاظ باقتراح النموذج.'}</span></div><button className="primary-button" disabled={saving||!validated||(warnings.length>0&&!ack)} onClick={save}><CheckCheck size={18}/>{saving?'جارٍ الحفظ…':'اعتماد المراجعة'}</button></div>
    {saved&&<p className="success-message" role="status"><CheckCheck size={18}/> تم اعتماد المراجعة وحفظ النتيجة.</p>}
  </section>;
}
