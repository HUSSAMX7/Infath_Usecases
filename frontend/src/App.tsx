import {lazy, Suspense, useCallback, useEffect, useRef, useState} from 'react';
import {ArrowUpLeft, CheckCheck, ChevronLeft, Clock3, CloudUpload, FileCheck2, FileText, FolderOpen, LayoutDashboard, LoaderCircle, Search, ShieldCheck, Sparkles, X} from 'lucide-react';
import {api} from './api';
import type {Document, Health, Invoice} from './types';
import {CATEGORIES, STATUS_LABELS} from './types';
const DocumentView=lazy(()=>import('./components/DocumentView').then(module=>({default:module.DocumentView})));

function Sidebar({health,onHome}:{health:Health|null;onHome:()=>void}){
  return <aside className="sidebar"><button className="brand" onClick={onHome}><span className="brand-icon"><ScanBrand/></span><span><strong>مِعيار</strong><small>INVOICE STUDIO</small></span></button>
    <div className="workspace-tag"><span className="workspace-icon">م</span><div><strong>مساحة التجربة</strong><small>بيئة محلية · مستخدم واحد</small></div></div>
    <span className="nav-caption">مساحة العمل</span><button className="nav-item selected" onClick={onHome}><LayoutDashboard size={19}/> الفواتير <ChevronLeft size={15}/></button>
    <div className="sidebar-note"><ShieldCheck size={24}/><h4>قراءة ذكية، قرار بشري</h4><p>استعرض الأصل، راجع القراءة، واعتمد البيانات التي تثق بها.</p></div>
    <div className="service-state"><span className={`mini-dot ${health?.ocr.available?'green':''}`}/><div><strong>LightOnOCR محلي</strong><small>{!health?'جارٍ التحقق':health.ocr.available?(health.ocr.state==='ready'?'النموذج محمّل وجاهز':'جاهز للتحميل عند المعالجة'):'الأوزان غير متوفرة'}</small></div></div><div className="sidebar-footer">نسخة تجريبية <span>v0.1</span></div>
  </aside>;
}
function ScanBrand(){return <><span/><span/><span/><span/></>;}

export default function App(){
  const [health,setHealth]=useState<Health|null>(null);
  const [invoices,setInvoices]=useState<Invoice[]>([]);
  const [selected,setSelected]=useState<string|null>(()=>new URLSearchParams(window.location.search).get('invoice'));
  const [document,setDocument]=useState<Document|null>(null);
  const [loading,setLoading]=useState(true);
  const [uploading,setUploading]=useState(false);
  const [dragging,setDragging]=useState(false);
  const [errors,setErrors]=useState<string[]>([]);
  const [search,setSearch]=useState('');
  const [filter,setFilter]=useState('all');
  const input=useRef<HTMLInputElement>(null);
  const selectedRef=useRef(selected); selectedRef.current=selected;
  const refresh=useCallback(async()=>{
    try{const [h,list]=await Promise.all([api.health(),api.list()]);setHealth(h);setInvoices(list.invoices);setLoading(false);}catch{setLoading(false);setErrors(old=>old.length?old:['تعذّر الاتصال بالخدمة المحلية. تأكد من تشغيل backend.']);}
  },[]);
  useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),2000);return()=>clearInterval(timer);},[refresh]);
  useEffect(()=>{
    if(!selected){setDocument(null);return;}
    setDocument(null); let stopped=false;
    const load=()=>api.get(selected).then(doc=>{if(!stopped&&selectedRef.current===selected)setDocument(doc);}).catch(e=>{if(!stopped)setErrors([e.message]);});
    void load(); const timer=setInterval(()=>void load(),2000);
    return()=>{stopped=true;clearInterval(timer);};
  },[selected]);
  function navigate(id:string|null){setSelected(id);window.history.replaceState({},'',id?`?invoice=${id}`:window.location.pathname);setErrors([]);window.scrollTo(0,0);}
  async function upload(files:File[]){
    if(!files.length||uploading)return;
    setUploading(true);setErrors([]);
    try{const result=await api.upload(files);setErrors(result.errors.map(e=>`${e.filename}: ${e.message}`));await refresh();if(result.invoices.length===1){setSelected(result.invoices[0].id);window.history.replaceState({},'',`?invoice=${result.invoices[0].id}`);}}
    catch(e){setErrors([e instanceof Error?e.message:'تعذّر رفع الملفات.']);}
    finally{setUploading(false);if(input.current)input.current.value='';}
  }
  const pending=invoices.filter(d=>['classified','needs_review'].includes(d.status)).length;
  const approved=invoices.filter(d=>d.status==='reviewed').length;
  const filtered=invoices.filter(d=>(filter==='all'||d.status===filter)&&`${d.filename} ${d.extracted_data?.supplier_name||''} ${d.extracted_data?.invoice_number||''}`.toLowerCase().includes(search.toLowerCase()));
  function update(doc:Document){setDocument(doc);void refresh();}
  return <div className="app-shell"><Sidebar health={health} onHome={()=>navigate(null)}/><div className="main-shell"><header className="topbar"><div className="breadcrumb"><span>مساحة العمل</span><ChevronLeft size={13}/><strong>الفواتير</strong></div><div className="topbar-meta"><span className="quiet-badge"><span className="mini-dot green"/> تجربة محلية</span><div className="avatar">م</div></div></header><main>
    {errors.length>0&&<div className="global-errors" role="alert"><div>{errors.map((e,i)=><p key={i}>{e}</p>)}</div><button className="icon-button" aria-label="إغلاق التنبيه" onClick={()=>setErrors([])}><X size={17}/></button></div>}
    {health?.extraction?.method==='regex'?<div className="configuration-note"><ShieldCheck size={16}/><span>استخراج الحقول والبنود بالقواعد محليًا. راجع القيم واختر التصنيف النهائي قبل الاعتماد.</span></div>:health&&!health.openai.configured&&<div className="configuration-note"><Sparkles size={16}/><span>قراءة LightOnOCR متاحة. لتفعيل استخراج الحقول والتصنيف، أضف <b dir="ltr">OPENAI_API_KEY</b> في ملف <b dir="ltr">.env</b> وأعد تشغيل التطبيق.</span></div>}
    {selected?(document?<Suspense fallback={<div className="loading-state">جارٍ فتح مساحة القراءة…</div>}><DocumentView document={document} onBack={()=>navigate(null)} onUpdate={update}/></Suspense>:<div className="loading-state"><LoaderCircle className="spin"/> جارٍ فتح الوثيقة…</div>):<>
      <div className="page-heading"><div><span className="eyebrow">من المستند إلى القرار</span><h1>فواتيرك، بوضوح أكبر<span className="heading-dot">.</span></h1><p>اقرأ المستند، راجع البيانات، واحفظ النتيجة بثقة.</p></div><button className="primary-button" disabled={uploading} onClick={()=>input.current?.click()}><CloudUpload size={18}/> رفع فاتورة</button></div>
      <div className="stats-grid"><Stat label="إجمالي الوثائق" value={invoices.length} icon={<FileText size={21}/>} tone="blue" detail="كل ملف يمثل فاتورة مستقلة"/><Stat label="بانتظار مراجعتك" value={pending} icon={<Clock3 size={21}/>} tone="amber" detail="نتائج جاهزة لاتخاذ القرار"/><Stat label="تم اعتمادها" value={approved} icon={<FileCheck2 size={21}/>} tone="green" detail="بيانات راجعتها وحفظتها"/></div>
      <div className={`upload-zone ${dragging?'dragging':''}`} onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={e=>{e.preventDefault();setDragging(false);void upload(Array.from(e.dataTransfer.files));}}>
        <div className="upload-illustration"><CloudUpload size={29}/></div><div className="upload-copy"><h3>{uploading?'جارٍ رفع وتجهيز المستندات…':'ابدأ بمستند، واترك القراءة علينا'}</h3><p>اسحب فواتيرك هنا أو <button disabled={uploading} onClick={()=>input.current?.click()}>اختر الملفات</button></p><div className="format-chips"><span>PDF</span><span>PNG</span><span>JPG</span><small>حتى {health?.limits.max_files??10} ملفات · {health?.limits.max_file_mb??20}MB للملف · {health?.limits.max_pages??10} صفحات</small></div></div><div className="upload-step"><span><ScanSmall/> قراءة</span><ChevronLeft size={13}/><span><Sparkles size={14}/> تحليل</span><ChevronLeft size={13}/><span><CheckCheck size={15}/> مراجعة</span></div>
      </div>
      <section className="panel documents-panel"><div className="documents-toolbar"><div><h2>الوثائق <span className="count">{invoices.length}</span></h2><p>كل القراءات والمراجعات في مكان واحد</p></div><div className="table-tools"><div className="search-box"><Search size={16}/><input aria-label="البحث في الفواتير" placeholder="ابحث عن فاتورة أو مورد…" value={search} onChange={e=>setSearch(e.target.value)}/></div><select aria-label="تصفية الحالة" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">كل الحالات</option>{Object.entries(STATUS_LABELS).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></div></div>
        {loading?<div className="loading-state"><LoaderCircle className="spin"/> جارٍ تحميل الوثائق…</div>:filtered.length?<div className="table-scroll"><table className="document-table"><thead><tr><th>الوثيقة / المورد</th><th>الإجمالي</th><th>التصنيف</th><th>الحالة</th><th>تاريخ الرفع</th><th/></tr></thead><tbody>{filtered.map(invoice=>{
          const cat=invoice.reviewed_by_user?invoice.final_classification:invoice.classification.key;
          return <tr key={invoice.id} onClick={()=>navigate(invoice.id)}><td><button className="document-cell" onClick={e=>{e.stopPropagation();navigate(invoice.id);}}><span className="file-icon"><FileText size={21}/></span><span><strong>{invoice.extracted_data?.supplier_name||invoice.filename}</strong><small dir="auto">{invoice.extracted_data?.invoice_number||invoice.filename}</small></span></button></td><td className="amount">{invoice.extracted_data?.total===null||!invoice.extracted_data?'—':invoice.extracted_data.total.toLocaleString('en-US',{maximumFractionDigits:2})}<small>{invoice.extracted_data?.currency||''}</small></td><td>{cat?<span className="category-badge">{CATEGORIES[cat]}</span>:invoice.reviewed_by_user||invoice.status==='needs_review'?<span className="muted">بلا تصنيف</span>:<span className="muted">—</span>}</td><td><span className={`status-badge ${invoice.status}`}>{['queued','processing'].includes(invoice.status)&&<LoaderCircle size={12} className="spin"/>}{STATUS_LABELS[invoice.status]}</span></td><td className="date-cell">{new Date(invoice.created_at).toLocaleDateString('ar-SA',{calendar:'gregory',month:'short',day:'numeric'})}</td><td><ArrowUpLeft size={17} className="row-arrow"/></td></tr>;
        })}</tbody></table></div>:<div className="empty-state"><div className="empty-paper"><span className="paper-fold"/><FileText size={35}/><i/><i/><i/><span className="empty-scan"><CheckCheck size={15}/></span></div><h3>{invoices.length?'لا توجد وثائق مطابقة':'أول فاتورة، أول خطوة'}</h3><p>{invoices.length?'جرّب البحث بكلمة مختلفة أو غيّر التصفية.':'ارفع فاتورة لتشاهد كيف قرأها النموذج، ثم راجع بياناتها واعتمدها.'}</p>{!invoices.length&&<button className="secondary-button" onClick={()=>input.current?.click()}><FolderOpen size={16}/> اختر أول فاتورة</button>}</div>}
        <div className="table-footer"><span><ShieldCheck size={14}/> النتائج لا تُعتمد دون مراجعتك</span><span>الحفظ على جهازك</span></div>
      </section><div className="workspace-bottom"><span>قراءة المستندات بـLightOnOCR · {health?.extraction?.method==='regex'?'استخراج بالقواعد محليًا':'تحليل وتصنيف عبر OpenAI'}</span><span>مِعيار <span className="tiny-dot">✦</span> وضوح في كل فاتورة</span></div>
    </>}
    <input ref={input} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp" className="sr-only" aria-label="رفع ملفات الفواتير" onChange={e=>void upload(Array.from(e.target.files||[]))}/>
  </main></div></div>;
}
function Stat({label,value,icon,tone,detail}:{label:string;value:number;icon:React.ReactNode;tone:string;detail:string}){return <div className="stat-card"><div><span>{label}</span><strong>{value.toLocaleString('en-US')}</strong><small>{detail}</small></div><div className={`stat-icon ${tone}`}>{icon}</div></div>;}
function ScanSmall(){return <FileText size={14}/>;}
