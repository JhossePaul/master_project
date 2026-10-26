import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const COMPONENTS: Components = {
  h1: (p) => (
    <h2 className="mt-4 mb-2 font-serif text-xl font-semibold" {...p} />
  ),
  h2: (p) => (
    <h3 className="mt-4 mb-2 font-serif text-lg font-semibold" {...p} />
  ),
  h3: (p) => <h4 className="mt-3 mb-1 font-semibold" {...p} />,
  h4: (p) => <h5 className="mt-3 mb-1 font-semibold" {...p} />,
  p: (p) => <p className="my-2" {...p} />,
  ul: (p) => <ul className="my-2 list-disc pl-5" {...p} />,
  ol: (p) => <ol className="my-2 list-decimal pl-5" {...p} />,
  a: (p) => <a className="text-green-600 underline" {...p} />,
  code: (p) => (
    <code className="rounded-sm bg-neutral-100 px-1 font-mono" {...p} />
  ),
  blockquote: (p) => (
    <blockquote
      className="my-2 border-l-2 border-border-strong pl-3 text-text-muted"
      {...p}
    />
  ),
  table: (p) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-left" {...p} />
    </div>
  ),
  th: (p) => (
    <th
      className="border-b border-border-strong px-2 py-1 font-semibold"
      {...p}
    />
  ),
  td: (p) => (
    <td className="border-b border-border px-2 py-1 align-top" {...p} />
  ),
};

/** Markdown de un documento del repo (guías), sin HTML crudo. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
