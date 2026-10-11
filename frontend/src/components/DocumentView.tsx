import { useState } from 'react';
import { ArrowRight, Braces, ChevronLeft, ChevronRight, Clock3, FileText, LoaderCircle, Maximize2, RotateCcw, ScanLine, TriangleAlert } from 'lucide-react';
import type {Document} from '../types';
import {STATUS_LABELS} from '../types';
import {api} from '../api';
import {OcrReading} from './OcrReading';
import {ReviewForm} from './ReviewForm';

const elapsed=(seconds:number|null)=>seconds===null?'—':seconds<1?`${Math.max(1,Math.round(seconds*1000))} مللي ثانية`:seconds<60?`${seconds.toFixed(1)} ث`:`${Math.floor(seconds/60)} د ${Math.round(seconds%60)} ث`;

export function DocumentView({document,onBack,onUpdate}:{document:Document;onBack:()=>void;onUpdate:(doc:Document)=>void}){
  const [pageIndex,setPageIndex]=useState(0);
  const [tab,setTab]=useState('formatted');
  const [zoom,setZoom]=useState(false);
  const [retrying,setRetrying]=useState(false);
  const [error,setError]=useState('');
  const [source,setSource]=useState<'original'|'regex'>(()=>{
    const requested=new URLSearchParams(window.location.search).get('source');
    return requested==='original'?'original':document.regex_result&&(requested==='regex'||document.review_source==='regex')?'regex':'original';
  });
  const [extracting,setExtracting]=useState(false);
  const originalRegex=document.analysis?.method==='regex';
  const result=source==='regex'?document.regex_result:null;
  const activeProposal=result?.proposal??document.ai_proposal;
  const activeAnalysis=result??document.analysis;
  const localRegex=activeAnalysis?.method==='regex';
  const activeReviewed=document.reviewed_by_user&&(document.review_source??'original')===source&&(source!=='regex'||!result?.revision||document.review_regex_revision===result.revision);
  const supplierName=activeReviewed?document.final_data?.supplier_name:activeProposal?.extracted_data.supplier_name;
  const displayedStatus=source==='regex'&&(document.review_source!=='regex'||(result?.revision&&document.review_regex_revision!==result.revision))?'needs_review':document.status;
  const page=document.pages[pageIndex]||document.pages[0];
  const processing=['queued','processing'].includes(document.status);
  async function retry(){setRetrying(true);setError('');try{onUpdate(await api.retry(document.id));}catch(e){setError(e instanceof Error?e.message:'تعذّرت إعادة المحاولة.');}finally{setRetrying(false);}}
  function changeSource(next:'original'|'regex'){setSource(next);const url=new URL(window.location.href);url.searchParams.set('source',next);window.history.replaceState({},'',url);}
  async function extractRegex(refresh=false){setExtracting(true);setError('');try{onUpdate(await api.extractRegex(document.id,refresh));changeSource('regex');}catch(e){setError(e instanceof Error?e.message:'تعذّر الاستخراج بالقواعد.');}finally{setExtracting(false);}}
  return <>
    <button className="back-button" onClick={onBack}><ArrowRight size={17}/> العودة إلى الفواتير</button>
    <div className="page-heading document-heading"><div><span className="eyebrow">مساحة قراءة الوثيقة</span><h1>{supplierName||document.filename}</h1><p><FileText size={14}/><span dir="auto">{document.filename}</span><span className="dot">·</span>{document.page_count} صفحة</p></div><span className={`status-badge ${displayedStatus}`}>{processing&&<LoaderCircle size={13} className="spin"/>}{STATUS_LABELS[displayedStatus]}</span></div>
    {processing&&<div className="processing-banner"><LoaderCircle size={20} className="spin"/><div><strong>{document.status==='queued'?'الفاتورة في طابور المعالجة':document.stage==='ocr'?`قراءة الصفحة ${document.current_page||1} من ${document.page_count}`:'استخراج الحقول وتحليل التصنيف'}</strong><p>تُحفظ القراءة أثناء المعالجة. يمكنك الرجوع للقائمة؛ المعالجة تستمر في الخلفية.</p></div></div>}
    {document.error&&!result&&<div className="failure-banner"><TriangleAlert size={22}/><div><strong>{document.error.stage==='analysis'?'قراءة المستند محفوظة، والتحليل يحتاج إعادة محاولة':'توقفت قراءة المستند'}</strong><p>{document.error.message}</p></div><button className="secondary-button" disabled={retrying} onClick={retry}><RotateCcw size={15}/>{retrying?'جارٍ الطلب…':'إعادة المحاولة'}</button></div>}
    {error&&<p className="error-inline" role="alert">{error}</p>}
    <div className="reading-heading"><div><ScanLine size={21}/><h2>الأصل وما قرأه النموذج</h2></div><div className="page-controls"><button aria-label="الصفحة السابقة" className="icon-button" disabled={pageIndex===0} onClick={()=>setPageIndex(pageIndex-1)}><ChevronRight size={17}/></button><span>صفحة {pageIndex+1} / {document.pages.length}</span><button aria-label="الصفحة التالية" className="icon-button" disabled={pageIndex>=document.pages.length-1} onClick={()=>setPageIndex(pageIndex+1)}><ChevronLeft size={17}/></button></div></div>
    <div className="comparison-grid">
      <section className="panel source-panel"><div className="panel-heading"><h3><FileText size={17}/> المستند الأصلي</h3><div><a className="text-button" href={document.file_url} target="_blank" rel="noreferrer">فتح الأصل</a><button className="icon-button" aria-label="تكبير المستند" onClick={()=>setZoom(!zoom)}><Maximize2 size={15}/></button></div></div><div className={`source-canvas ${zoom?'zoomed':''}`}><img src={page.preview_url} alt={`المستند الأصلي — صفحة ${page.number}`} loading="lazy"/></div></section>
      <section className="panel reading-panel"><div className="panel-heading"><h3><ScanLine size={17}/> قراءة LightOnOCR</h3><div className="reading-tabs"><button className={tab==='formatted'?'active':''} onClick={()=>setTab('formatted')}>المستند المقروء</button><button className={tab==='raw'?'active':''} onClick={()=>setTab('raw')}>النص الخام</button></div></div>
        <div className="reading-canvas" role="region" aria-label="محتوى قراءة النموذج" tabIndex={0}>{page.text?(tab==='formatted'?<OcrReading text={page.text}/>:<pre className="raw-text" dir="auto">{page.text}</pre>):<div className="reading-placeholder"><ScanLine size={36}/><h3>{processing?'القراءة في طريقها…':'لا توجد قراءة لهذه الصفحة بعد'}</h3><p>سيظهر هنا النص والجداول كما قرأها النموذج.</p></div>}</div>
        <div className="reading-footer"><span className={`mini-dot ${page.status==='complete'?'green':''}`}/>{page.status==='complete'?'قراءة مكتملة':page.status==='reading'?'قراءة جزئية — قيد المعالجة':page.status==='failed'?'قراءة غير مكتملة':'بانتظار القراءة'}<span className="reading-time"><Clock3 size={13}/>{elapsed(page.seconds)}</span></div>
      </section>
    </div>
    <section className="extraction-choice panel" aria-label="مصدر استخراج الحقول"><div><strong>{localRegex?'Regex · استخراج محلي':'مصدر استخراج الحقول'}</strong><p>{localRegex?'قواعد للحقول وقارئ للجداول. القيم غير المحسومة تبقى فارغة للمراجعة.':'جرّب القواعد على قراءة OCR نفسها، ثم اختر النتيجة التي تراجعها.'}</p></div><div className="extraction-actions">
      {!originalRegex&&document.ai_proposal&&<button className={source==='original'?'primary-button':'secondary-button'} onClick={()=>changeSource('original')}>نتيجة النموذج المحفوظة</button>}
      {!originalRegex&&<button className={source==='regex'?'primary-button':'secondary-button'} disabled={extracting||processing||document.pages.some(p=>p.status!=='complete')} onClick={()=>extractRegex()}>{extracting?<LoaderCircle size={16} className="spin"/>:<Braces size={16}/>} {document.regex_result?'نتيجة Regex':'استخراج بـRegex'}</button>}
      {(originalRegex||document.regex_result)&&<button className="secondary-button" disabled={extracting||processing||document.pages.some(p=>p.status!=='complete')} onClick={()=>extractRegex(true)}><RotateCcw size={16}/> إعادة الاستخراج بـRegex</button>}
      {localRegex&&<span className="quiet-badge">دون استدعاء LLM</span>}
    </div></section>
    {activeProposal?<ReviewForm key={`${document.id}-${source}-${activeAnalysis?.revision??'legacy'}`} source={source} document={{...document,ai_proposal:activeProposal,analysis:activeAnalysis}} onSaved={onUpdate}/>:<div className="awaiting-analysis"><Braces size={23}/><div><h3>الحقول تظهر بعد اكتمال الاستخراج</h3><p>قراءة LightOnOCR مستقلة عن استخراج الحقول، وتظل متاحة حتى لو توقف الاستخراج.</p></div></div>}
    <details className="technical-details"><summary><Braces size={16}/> تفاصيل التشغيل والتشخيص</summary><div className="technical-grid"><div><small>نموذج القراءة</small><strong dir="ltr">{document.ocr_model}</strong></div><div><small>طريقة الاستخراج المعروضة</small><strong dir="ltr">{activeAnalysis?.model||'لم يكتمل الاستخراج'}</strong></div><div><small>زمن الاستخراج</small><strong>{elapsed(activeAnalysis?.seconds??null)}</strong></div><div><small>آخر محاولة</small><strong>{elapsed(document.attempt_seconds)}</strong></div></div>
      <h4>النص المستخدم للاستخراج</h4><pre dir="auto">{document.analysis_input||document.llm_input||document.ocr_text||'لم تبدأ مرحلة الاستخراج بعد.'}</pre><h4>{localRegex?'القواعد ومصادر القيم وحالات عدم الحسم':'النتيجة الأصلية للتحليل'}</h4><pre dir="ltr">{JSON.stringify(activeAnalysis?.raw_response??document.failure_details??{},null,2)}</pre>
    </details>
  </>;
}
