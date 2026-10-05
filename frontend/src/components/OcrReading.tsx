import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';

export function OcrReading({text}: {text:string}) {
  // A Latin logo at the start must not flip the entire Arabic invoice/table.
  const plain=text.replace(/<[^>]*>/g,'');
  const arabic=(plain.match(/[\u0621-\u064a]/g)||[]).length;
  const latin=(plain.match(/[A-Za-z]/g)||[]).length;
  return <div className="ocr-reading" data-testid="ocr-reading" dir={arabic>latin?'rtl':'ltr'}>
    <ReactMarkdown rehypePlugins={[rehypeRaw, rehypeSanitize]} components={{img:()=>null, a:({children})=><span>{children}</span>}}>{text}</ReactMarkdown>
  </div>;
}
