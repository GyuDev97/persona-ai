import { Fragment, useState, type ReactNode } from "react";

/**
 * 안전한 Markdown 렌더러. 문자열을 React 요소로만 만들고 dangerouslySetInnerHTML 을 쓰지 않으므로
 * 원문에 들어 있는 HTML 태그·스크립트는 실행되지 않고 글자 그대로 보인다.
 * 링크는 http/https 만 허용하고(javascript:, data: 등은 링크가 아닌 글자로 표시) 새 탭 + noopener noreferrer 로 연다.
 * 지원: 제목(#), 문단, 목록(중첩·번호), 인용(>), 코드(``` / `), 굵게/기울임, 링크, 자동 링크, 구분선.
 */

export function safeHref(raw: string): string | null {
  try {
    const u = new URL(raw.trim());
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

function Link({ href, children }: { href: string; children: ReactNode }) {
  const safe = safeHref(href);
  if (!safe) return <>{children}</>;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer nofollow" title={`${safe} (새 탭에서 열림)`}>
      {children}
    </a>
  );
}

const INLINE = /(`[^`\n]+`)|\[([^\]\n]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)|\*\*([^*\n]+)\*\*|__([^_\n]+)__|(?<![\w*])\*([^*\s][^*\n]*?)\*(?![\w*])|(https?:\/\/[^\s<>]+)/g;

function inline(text: string, keyBase = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyBase}-${n++}`;
    if (m[1]) out.push(<code key={key}>{m[1].slice(1, -1)}</code>);
    else if (m[2] !== undefined) out.push(<Link key={key} href={m[3]}>{inline(m[2], key)}</Link>);
    else if (m[4] !== undefined || m[5] !== undefined) out.push(<strong key={key}>{inline(m[4] ?? m[5], key)}</strong>);
    else if (m[6] !== undefined) out.push(<em key={key}>{inline(m[6], key)}</em>);
    else if (m[7]) {
      let url = m[7];
      let tail = "";
      while (/[.,;:!?'"”’)\]]$/.test(url) && !(url.endsWith(")") && url.includes("("))) {  // 문장 부호는 링크에서 뺀다
        tail = url.slice(-1) + tail;
        url = url.slice(0, -1);
      }
      out.push(<Link key={key} href={url}>{url}</Link>);
      if (tail) out.push(tail);
    }
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

interface ListNode { ordered: boolean; items: { text: string; children: ListNode[] }[] }

function buildList(lines: { indent: number; ordered: boolean; text: string }[]): ListNode {
  const root: ListNode = { ordered: lines[0].ordered, items: [] };
  const stack: { indent: number; list: ListNode }[] = [{ indent: lines[0].indent, list: root }];
  for (const l of lines) {
    while (stack.length > 1 && l.indent < stack[stack.length - 1].indent) stack.pop();
    let top = stack[stack.length - 1];
    if (l.indent > top.indent) {
      const parent = top.list.items[top.list.items.length - 1];
      if (parent) {
        const child: ListNode = { ordered: l.ordered, items: [] };
        parent.children.push(child);
        stack.push({ indent: l.indent, list: child });
        top = stack[stack.length - 1];
      }
    }
    top.list.items.push({ text: l.text, children: [] });
  }
  return root;
}

function renderList(node: ListNode, key: string): ReactNode {
  const Tag = node.ordered ? "ol" : "ul";
  return (
    <Tag key={key}>
      {node.items.map((it, i) => (
        <li key={i}>
          {inline(it.text, `${key}-${i}`)}
          {it.children.map((c, j) => renderList(c, `${key}-${i}-${j}`))}
        </li>
      ))}
    </Tag>
  );
}

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

export function renderMarkdown(src: string): ReactNode[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${k++}`;
    if (!line.trim()) { i++; continue; }
    const fence = line.match(/^\s*```(\S*)/);
    if (fence) {  // 코드 블록: 내용은 해석하지 않고 그대로 보여 준다
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(<pre key={key} className="md-code"><code>{body.join("\n")}</code></pre>);
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (h) {
      const Tag = `h${h[1].length}` as "h1";
      out.push(<Tag key={key}>{inline(h[2], key)}</Tag>);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push(<hr key={key} />); i++; continue; }
    if (/^\s*>/.test(line)) {
      const q: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(<blockquote key={key}>{q.map((t, j) => <Fragment key={j}>{j > 0 && <br />}{inline(t, `${key}-${j}`)}</Fragment>)}</blockquote>);
      continue;
    }
    if (LIST.test(line)) {
      const items: { indent: number; ordered: boolean; text: string }[] = [];
      while (i < lines.length) {
        const m = lines[i].match(LIST);
        if (m) items.push({ indent: m[1].replace(/\t/g, "  ").length, ordered: /\d/.test(m[2]), text: m[3] });
        else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) items[items.length - 1].text += " " + lines[i].trim();  // 들여쓴 이어지는 줄
        else break;
        i++;
      }
      out.push(renderList(buildList(items), key));
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(#{1,6}\s|```|>)/.test(lines[i]) && !LIST.test(lines[i])) para.push(lines[i++]);
    out.push(<p key={key}>{para.map((t, j) => <Fragment key={j}>{j > 0 && " "}{inline(t, `${key}-${j}`)}</Fragment>)}</p>);
  }
  return out;
}

export function MarkdownView({ source }: { source: string }) {
  return <div className="md-body">{renderMarkdown(source)}</div>;
}

/** 미리보기(렌더링) / 원본(Markdown 텍스트) 전환 보기. */
export function MarkdownPane({ source, maxHeight = 520 }: { source: string; maxHeight?: number }) {
  const [mode, setMode] = useState<"preview" | "raw">("preview");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 클립보드를 쓸 수 없는 환경: 원본 보기에서 직접 복사한다 */
    }
  };
  return (
    <div className="md-pane">
      <div className="row between wrap" style={{ marginBottom: 6 }}>
        <div className="seg" role="tablist" aria-label="보기 방식">
          <button role="tab" aria-selected={mode === "preview"} className={mode === "preview" ? "on" : ""} onClick={() => setMode("preview")}>미리보기</button>
          <button role="tab" aria-selected={mode === "raw"} className={mode === "raw" ? "on" : ""} onClick={() => setMode("raw")}>원본 Markdown</button>
        </div>
        <button className="ghost sm" onClick={copy}>{copied ? "복사됨" : "원본 복사"}</button>
      </div>
      <div className="md-scroll" style={{ maxHeight }}>
        {mode === "preview" ? <MarkdownView source={source} /> : <pre style={{ margin: 0, maxHeight: "none", border: "none" }}>{source}</pre>}
      </div>
    </div>
  );
}
