import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {ReviewForm} from './ReviewForm';
import {OcrReading} from './OcrReading';
import {api} from '../api';
import type {Document} from '../types';

vi.mock('../api',()=>({api:{validate:vi.fn(),review:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const proposal={extracted_data:{invoice_number:'INV-1',supplier_name:'Original',invoice_date:'2024-06-02',subtotal:100,vat:15,total:115,currency:'SAR'},items:[{description:'Laptop',quantity:1,unit_price:100,total:100}],classification:'computers' as const,confidence:.96,reason:'Laptop'};
const document:Document={id:'one',filename:'sample.png',status:'classified',stage:null,current_page:null,page_count:1,size_bytes:100,
  created_at:'2024-06-02T00:00:00Z',updated_at:'2024-06-02T00:00:00Z',file_url:'/api/invoices/one/file',
  extracted_data:proposal.extracted_data,classification:{key:'computers',label:'أجهزة كمبيوتر',confidence:.96},
  ai_proposal:proposal,final_data:null,final_items:null,reviewed_by_user:false,reviewed_at:null,final_classification:null,
  warnings:[],error:null,pages:[],ocr_text:'',ocr_model:'TEST ONLY',llm_input:null,analysis:null,failure_details:null,
  attempt_seconds:null,warnings_acknowledged:false};

describe('review and OCR reading',()=>{
  it('requires a new review for a changed regex revision and submits that revision',async()=>{
    vi.mocked(api.validate).mockResolvedValue({warnings:[]});vi.mocked(api.review).mockResolvedValue(document);
    const revision='1'.repeat(64);
    const compared:Document={...document,reviewed_by_user:true,review_source:'regex',review_regex_revision:'0'.repeat(64),
      final_data:{...proposal.extracted_data,supplier_name:'Previous final'},
      ai_proposal:{...proposal,extracted_data:{...proposal.extracted_data,supplier_name:'New extraction'},classification:null,confidence:null},
      analysis:{method:'regex',model:'Regex v2',revision,seconds:.005,raw_response:{},usage:null}};
    render(<ReviewForm source="regex" document={compared} onSaved={vi.fn()}/>);
    expect(screen.getByLabelText('اسم المورد')).toHaveValue('New extraction');
    await waitFor(()=>expect(screen.getByRole('button',{name:'اعتماد المراجعة'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'اعتماد المراجعة'}));
    await waitFor(()=>expect(api.review).toHaveBeenCalled());
    expect(vi.mocked(api.review).mock.calls[0][1].regex_revision).toBe(revision);
    expect(compared.final_data?.supplier_name).toBe('Previous final');
  });
  it('keeps human corrections when the reviewed regex revision is unchanged',()=>{
    vi.mocked(api.validate).mockResolvedValue({warnings:[]});
    const revision='1'.repeat(64);
    const reviewed:Document={...document,reviewed_by_user:true,review_source:'regex',review_regex_revision:revision,
      final_data:{...proposal.extracted_data,supplier_name:'Human correction'},
      analysis:{method:'regex',model:'Regex v2',revision,seconds:.005,raw_response:{},usage:null}};
    render(<ReviewForm source="regex" document={reviewed} onSaved={vi.fn()}/>);
    expect(screen.getByLabelText('اسم المورد')).toHaveValue('Human correction');
  });
  it('reviews regex separately from a previous AI review without presenting model confidence',async()=>{
    vi.mocked(api.validate).mockResolvedValue({warnings:[]});vi.mocked(api.review).mockResolvedValue(document);
    const regexProposal={...proposal,extracted_data:{...proposal.extracted_data,supplier_name:'Regex Supplier'},classification:null,confidence:null};
    const compared:Document={...document,reviewed_by_user:true,review_source:'original',final_data:{...proposal.extracted_data,supplier_name:'Previous final'},ai_proposal:regexProposal,analysis:{method:'regex',model:'Regex',seconds:.005,raw_response:{},usage:null}};
    render(<ReviewForm source="regex" document={compared} onSaved={vi.fn()}/>);
    expect(screen.getByLabelText('اسم المورد')).toHaveValue('Regex Supplier');
    expect(screen.getByText('لم يُقترح تصنيف')).toBeInTheDocument();
    expect(screen.queryByText('تقدير الثقة')).not.toBeInTheDocument();
    await waitFor(()=>expect(screen.getByRole('button',{name:'اعتماد المراجعة'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'اعتماد المراجعة'}));
    await waitFor(()=>expect(api.review).toHaveBeenCalled());
    expect(vi.mocked(api.review).mock.calls[0][1].source).toBe('regex');
    expect(proposal.extracted_data.supplier_name).toBe('Original');
  });
  it('changes final fields/category without mutating the AI proposal',async()=>{
    vi.mocked(api.validate).mockResolvedValue({warnings:[]});vi.mocked(api.review).mockResolvedValue(document);
    render(<ReviewForm document={document} onSaved={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText('اسم المورد'),{target:{value:'Corrected'}});
    fireEvent.change(screen.getByLabelText('التصنيف النهائي'),{target:{value:'tech_accessories'}});
    await waitFor(()=>expect(screen.getByRole('button',{name:'اعتماد المراجعة'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'اعتماد المراجعة'}));
    await waitFor(()=>expect(api.review).toHaveBeenCalled());
    expect(vi.mocked(api.review).mock.calls[0][1].extracted_data.supplier_name).toBe('Corrected');
    expect(vi.mocked(api.review).mock.calls[0][1].final_classification).toBe('tech_accessories');
    expect(proposal.extracted_data.supplier_name).toBe('Original');
    expect(proposal.classification).toBe('computers');
  });
  it('requires warning acknowledgement and permits null classification',async()=>{
    vi.mocked(api.validate).mockResolvedValue({warnings:[{code:'missing_vat',message:'الضريبة ناقصة'}]});vi.mocked(api.review).mockResolvedValue(document);
    render(<ReviewForm document={document} onSaved={vi.fn()}/>);
    await screen.findByText('الضريبة ناقصة');
    expect(screen.getByRole('button',{name:'اعتماد المراجعة'})).toBeDisabled();
    fireEvent.change(screen.getByLabelText('التصنيف النهائي'),{target:{value:''}});
    await waitFor(()=>expect(api.validate).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(()=>expect(screen.getByRole('button',{name:'اعتماد المراجعة'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'اعتماد المراجعة'}));
    await waitFor(()=>expect(api.review).toHaveBeenCalled());
    expect(vi.mocked(api.review).mock.calls[0][1].final_classification).toBeNull();
  });
  it('renders OCR tables while removing scripts, event handlers and remote images',()=>{
    const {container}=render(<OcrReading text={'# فاتورة\n<table><tr><td>4500</td></tr></table><script>alert(1)</script><img src="https://example.com/tracker" onerror="alert(1)" />'}/>);
    expect(screen.getByText('4500')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.innerHTML).not.toContain('onerror');
  });
  it('preserves Arabic reading direction even when the invoice begins with a Latin logo',()=>{
    const {rerender}=render(<OcrReading text={'# XYZ للمقاولات والصيانة\nفاتورة ضريبية\n<table><tr><td>المجموع الفرعي</td></tr></table>'}/>);
    expect(screen.getByTestId('ocr-reading')).toHaveAttribute('dir','rtl');
    rerender(<OcrReading text={'# XYZ Invoice\nCustomer: شركة\nItems, quantity, unit price and invoice total'}/>);
    expect(screen.getByTestId('ocr-reading')).toHaveAttribute('dir','ltr');
  });
});
