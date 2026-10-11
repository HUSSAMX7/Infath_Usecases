import { useState } from 'react';
import { ArrowRight, Braces, ChevronLeft, ChevronRight, Clock3, FileText, LoaderCircle, Maximize2, RotateCcw, ScanLine, TriangleAlert } from 'lucide-react';
import type {Document} from '../types';
import {STATUS_LABELS} from '../types';
import {api} from '../api';
import {OcrReading} from './OcrReading';
import {ReviewForm} from './ReviewForm';

const elapsed=(seconds:number|null)=>seconds===null?'—':seconds<60?`${seconds.toFixed(1)} ث`:`${Math.floor(seconds/60)} د ${Math.round(seconds%60)} ث`;

export function DocumentView({document,onBack,onUpdate}:{document:Document;onBack:()=>void;onUpdate:(doc:Document)=>void}){
  const [pageIndex,setPageIndex]=useState(0);
  const [tab,setTab]=useState('formatted');
  const [zoom,setZoom]=useState(false);
  const [retrying,setRetrying]=useState(false);
  const [error,setError]=useState('');
  const page=document.pages[pageIndex]||document.pages[0];
  const processing=['queued','processing'].includes(document.status);
  async function retry(){setRetrying(true);setError('');try{onUpdate(await api.retry(document.id));}catch(e){setError(e instanceof Error?e.message:'تعذّرت إعادة المحاولة.');}finally{setRetrying(false);}}
  return <>
    <button className="back-button" onClick={onBack}><ArrowRight size={17}/> العودة إلى الفواتير</button>
    <div className="page-heading document-heading"><div><span className="eyebrow">مساحة قراءة الوثيقة</span><h1>{document.extracted_data?.supplier_name||document.filename}</h1><p><FileText size={14}/><span dir="auto">{document.filename}</span><span className="dot">·</span>{document.page_count} صفحة</p></div><span className={`status-badge ${document.status}`}>{processing&&<LoaderCircle size={13} className="spin"/>}{STATUS_LABELS[document.status]}</span></div>
    {processing&&<div className="processing-banner"><LoaderCircle size={20} className="spin"/><div><strong>{document.status==='queued'?'الفاتورة في طابور المعالجة':document.stage==='ocr'?`قراءة الصفحة ${document.current_page||1} من ${document.page_count}`:'استخراج الحقول وتحليل التصنيف'}</strong><p>تُحفظ القراءة أثناء المعالجة. يمكنك الرجوع للقائمة؛ المعالجة تستمر في الخلفية.</p></div></div>}
    {document.error&&<div className="failure-banner"><TriangleAlert size={22}/><div><strong>{document.error.stage==='analysis'?'قراءة المستند محفوظة، والتحليل يحتاج إعادة محاولة':'توقفت قراءة المستند'}</strong><p>{document.error.message}</p></div><button className="secondary-button" disabled={retrying} onClick={retry}><RotateCcw size={15}/>{retrying?'جارٍ الطلب…':'إعادة المحاولة'}</button></div>}
    {error&&<p className="error-inline" role="alert">{error}</p>}
    <div className="reading-heading"><div><ScanLine size={21}/><h2>الأصل وما قرأه النموذج</h2></div><div className="page-controls"><button aria-label="الصفحة السابقة" className="icon-button" disabled={pageIndex===0} onClick={()=>setPageIndex(pageIndex-1)}><ChevronRight size={17}/></button><span>صفحة {pageIndex+1} / {document.pages.length}</span><button aria-label="الصفحة التالية" className="icon-button" disabled={pageIndex>=document.pages.length-1} onClick={()=>setPageIndex(pageIndex+1)}><ChevronLeft size={17}/></button></div></div>
    <div className="comparison-grid">
      <section className="panel source-panel"><div className="panel-heading"><h3><FileText size={17}/> المستند الأصلي</h3><div><a className="text-button" href={document.file_url} target="_blank" rel="noreferrer">فتح الأصل</a><button className="icon-button" aria-label="تكبير المستند" onClick={()=>setZoom(!zoom)}><Maximize2 size={15}/></button></div></div><div className={`source-canvas ${zoom?'zoomed':''}`}><img src={page.preview_url} alt={`المستند الأصلي — صفحة ${page.number}`} loading="lazy"/></div></section>
      <section className="panel reading-panel"><div className="panel-heading"><h3><ScanLine size={17}/> قراءة LightOnOCR</h3><div className="reading-tabs"><button className={tab==='formatted'?'active':''} onClick={()=>setTab('formatted')}>المستند المقروء</button><button className={tab==='raw'?'active':''} onClick={()=>setTab('raw')}>النص الخام</button></div></div>
        <div className="reading-canvas" role="region" aria-label="محتوى قراءة النموذج" tabIndex={0}>{page.text?(tab==='formatted'?<OcrReading text={page.text}/>:<pre className="raw-text" dir="auto">{page.text}</pre>):<div className="reading-placeholder"><ScanLine size={36}/><h3>{processing?'القراءة في طريقها…':'لا توجد قراءة لهذه الصفحة بعد'}</h3><p>سيظهر هنا النص والجداول كما قرأها النموذج.</p></div>}</div>
        <div className="reading-footer"><span className={`mini-dot ${page.status==='complete'?'green':''}`}/>{page.status==='complete'?'قراءة مكتملة':page.status==='reading'?'قراءة جزئية — قيد المعالجة':page.status==='failed'?'قراءة غير مكتملة':'بانتظار القراءة'}<span className="reading-time"><Clock3 size={13}/>{elapsed(page.seconds)}</span></div>
      </section>
    </div>
    {document.ai_proposal?<ReviewForm key={document.id} document={document} onSaved={onUpdate}/>:<div className="awaiting-analysis"><Braces size={23}/><div><h3>الحقول والتصنيف تظهر بعد اكتمال التحليل</h3><p>قراءة LightOnOCR أعلاه مستقلة عن نتيجة OpenRouter، وتظل متاحة حتى لو توقف التحليل.</p></div></div>}
    <details className="technical-details"><summary><Braces size={16}/> تفاصيل التشغيل والتشخيص</summary><div className="technical-grid"><div><small>نموذج القراءة</small><strong dir="ltr">{document.ocr_model}</strong></div><div><small>نموذج التحليل</small><strong dir="ltr">{document.analysis?.model||'لم يكتمل التحليل'}</strong></div><div><small>زمن التحليل</small><strong>{elapsed(document.analysis?.seconds??null)}</strong></div><div><small>آخر محاولة</small><strong>{elapsed(document.attempt_seconds)}</strong></div></div>
      <h4>النص المرسل للتحليل</h4><pre dir="auto">{document.llm_input||'لم يُرسل طلب تحليل بعد.'}</pre><h4>النتيجة الأصلية للتحليل</h4><pre dir="ltr">{JSON.stringify(document.analysis?.raw_response??document.failure_details??{},null,2)}</pre>
    </details>
  </>;
}
