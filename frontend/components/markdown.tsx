import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:tracking-tight prose-h1:text-xl prose-h2:text-base prose-h3:text-sm prose-a:text-accent prose-a:no-underline hover:prose-a:underline prose-table:text-[13px] prose-th:text-left prose-hr:border-line">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
