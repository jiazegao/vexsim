import type { MouseEvent, ReactNode } from "react";
import { Fragment } from "react";
import type { Block, Inline } from "../markdown";

/** Where a link goes: its address for the browser (to open in a new tab, or to copy), and
 * what a click does instead, if the app can go there itself. */
export interface LinkTo {
  href: string;
  go?: () => void; // within the app
}

/** A document's blocks, drawn (the Guide page's). Its headings carry their ids with `prefix`
 * before them, so they can't be taken for anything else on the page. */
export function Markdown(props: { blocks: Block[]; prefix: string; link: (href: string) => LinkTo; picture: (src: string) => string }) {
  const inline = (inlines: Inline[]): ReactNode =>
    inlines.map((part, i) => {
      switch (part.kind) {
        case "text":
          return <Fragment key={i}>{part.text}</Fragment>;
        case "code":
          return <code key={i}>{part.text}</code>;
        case "strong":
          return <strong key={i}>{inline(part.children)}</strong>;
        case "em":
          return <em key={i}>{inline(part.children)}</em>;
        case "break":
          return <br key={i} />;
        case "image":
          return <img key={i} src={props.picture(part.src)} alt={part.alt} loading="lazy" />;
        case "link": {
          const to = props.link(part.href);
          const follow = (event: MouseEvent) => {
            // a click goes there in the app; Ctrl, Shift or the middle button stay the browser's
            if (!to.go || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            to.go();
          };
          return (
            <a key={i} href={to.href} onClick={follow} {...(to.go ? {} : { target: "_blank", rel: "noreferrer noopener" })}>
              {inline(part.children)}
            </a>
          );
        }
      }
    });

  const block = (item: Block, key: number): ReactNode => {
    switch (item.kind) {
      case "heading": {
        const Tag = `h${Math.min(item.level, 6)}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
        const to = props.link(`#${item.id}`);
        return (
          <Tag key={key} id={props.prefix + item.id} tabIndex={-1}>
            {inline(item.children)}
            <a
              className="anchor"
              href={to.href}
              onClick={(event) => {
                event.preventDefault();
                to.go?.();
              }}
              aria-label={`The address of "${item.text}"`}
              title="This heading's address"
            />
          </Tag>
        );
      }
      case "paragraph":
        return <p key={key}>{inline(item.children)}</p>;
      case "code":
        return (
          <pre key={key} data-language={item.language || undefined}>
            <code>{item.text}</code>
          </pre>
        );
      case "rule":
        return <hr key={key} />;
      case "quote":
        return <blockquote key={key}>{item.blocks.map(block)}</blockquote>;
      case "table":
        return (
          <div key={key} className="table-scroll">
            <table>
              <thead>
                <tr>
                  {item.head.map((cell, i) => (
                    <th key={i} style={{ textAlign: item.align[i] ?? undefined }}>
                      {inline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {item.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, i) => (
                      <td key={i} style={{ textAlign: item.align[i] ?? undefined }}>
                        {inline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case "list": {
        const items = item.items.map((entry, i) => {
          // a tight list's items are their text, not paragraphs of it
          const body = entry.blocks.map((inner, k) => (item.tight && inner.kind === "paragraph" ? <Fragment key={k}>{inline(inner.children)}</Fragment> : block(inner, k)));
          return (
            <li key={i} className={entry.checked === null ? undefined : "box"}>
              {entry.checked !== null && <input type="checkbox" checked={entry.checked} readOnly disabled aria-label={entry.checked ? "done" : "to do"} />}
              {body}
            </li>
          );
        });
        return item.ordered ? (
          <ol key={key} start={item.start}>
            {items}
          </ol>
        ) : (
          <ul key={key}>{items}</ul>
        );
      }
    }
  };

  return <>{props.blocks.map(block)}</>;
}
