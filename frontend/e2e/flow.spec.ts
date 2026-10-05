import {test,expect} from '@playwright/test';
import path from 'node:path';

test('upload → OCR → analysis → corrected human review → persistent result',async({page,request})=>{
  const pageErrors:string[]=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto('/');
  await page.getByLabel('رفع ملفات الفواتير').setInputFiles(path.resolve('../.local/e2e-fixtures/invoice.png'));
  await expect(page.getByRole('heading',{name:'راجع، ثم اعتمد'})).toBeVisible();
  await expect(page.getByTestId('ocr-reading')).toContainText('TEST ONLY');
  const image=page.getByRole('img',{name:'المستند الأصلي — صفحة 1'});
  await expect(image).toBeVisible();
  expect(await image.evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByRole('button',{name:'اعتماد المراجعة'})).toBeDisabled();
  await page.getByLabel('اسم المورد',{exact:true}).fill('المورد المصحح');
  await page.getByLabel('التصنيف النهائي').selectOption('tech_accessories');
  await page.getByRole('checkbox').check();
  await expect(page.getByRole('button',{name:'اعتماد المراجعة'})).toBeEnabled();
  await page.getByRole('button',{name:'اعتماد المراجعة'}).click();
  await expect(page.getByText('تم اعتماد المراجعة وحفظ النتيجة.')).toBeVisible();
  const id=new URL(page.url()).searchParams.get('invoice');
  const saved=await (await request.get(`/api/invoices/${id}`)).json();
  expect(saved.ai_proposal.classification).toBe('computers');
  expect(saved.ai_proposal.extracted_data.supplier_name).toBe('المورد');
  expect(saved.final_classification).toBe('tech_accessories');
  expect(saved.final_data.supplier_name).toBe('المورد المصحح');
  expect(saved.reviewed_by_user).toBe(true);
  await page.reload();
  await expect(page.getByLabel('اسم المورد',{exact:true})).toHaveValue('المورد المصحح');
  await page.getByRole('button',{name:'النص الخام',exact:true}).click();
  await expect(page.locator('.raw-text')).toContainText('TEST ONLY');
  expect(pageErrors).toEqual([]);
});

test('PDF pages and responsive document reading',async({page})=>{
  await page.goto('/');
  await page.getByLabel('رفع ملفات الفواتير').setInputFiles(path.resolve('../.local/e2e-fixtures/two-pages.pdf'));
  await expect(page.getByRole('heading',{name:'راجع، ثم اعتمد'})).toBeVisible();
  await expect(page.getByTestId('ocr-reading')).toContainText('page-1.png');
  await page.getByRole('button',{name:'الصفحة التالية'}).click();
  await expect(page.getByTestId('ocr-reading')).toContainText('page-2.png');
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('heading',{name:'الأصل وما قرأه النموذج'})).toBeVisible();
  const bounds=await page.locator('.comparison-grid').evaluate(el=>({width:el.clientWidth,columns:getComputedStyle(el).gridTemplateColumns}));
  expect(bounds.width).toBeLessThan(390);
  expect(bounds.columns.trim().split(' ')).toHaveLength(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
