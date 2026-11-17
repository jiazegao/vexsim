import { useEffect, useMemo, useRef, useState } from "react";
import { formatPlace } from "../address";
import { api } from "../api";
import type { LinkTo } from "../components/Markdown";
import { Markdown } from "../components/Markdown";
import { resolveLink, resolvePicture } from "../guide";
import type { Block } from "../markdown";
import { headings, parse } from "../markdown";
import type { GuideDocument, GuideIndex } from "../protocol";

const PREFIX = "guide-"; // before a heading's id on the page: a heading called "Sidebar" isn't the sidebar

/** vexsim's own documents, in the app (phase 15.4): the user guide, calibrating step by step,
 * programming, and the rest of docs/. Each document and each heading has its address, and the
 * documents' links to each other go from one to the next here. */
export function GuidePage(props: { doc: string; at: string | null; onGo: (doc: string, at: string | null) => void }) {
  const { onGo } = props;
  const [index, setIndex] = useState<GuideIndex | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [read, setRead] = useState<Record<string, Block[]>>({}); // the documents read so far
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .guide()
      .then(setIndex)
      .catch((error) => setProblem((error as Error).message));
  }, []);

  const documents = index?.documents ?? [];
  const current: GuideDocument | null = documents.find((d) => d.id === props.doc) ?? documents[0] ?? null;
  const id = current?.id ?? null;
  const available = index?.available ?? false;
  const blocks = id ? read[id] : undefined;
  useEffect(() => {
    if (!available || !id || blocks) return;
    let wanted = true;
    setProblem(null);
    api
      .guideDocument(id)
      .then((found) => wanted && setRead((all) => ({ ...all, [id]: parse(found.text) })))
      .catch((error) => wanted && setProblem((error as Error).message));
    return () => {
      wanted = false;
    };
  }, [available, id, blocks]);

  // at the heading the address names, once its document is drawn; at the top of another
  const show = (at: string | null) => {
    const heading = at ? document.getElementById(PREFIX + at) : null;
    if (heading) heading.scrollIntoView({ block: "start" });
    else body.current?.scrollTo({ top: 0 });
  };
  useEffect(() => {
    if (blocks) show(props.at);
  }, [blocks, id, props.at]);

  const sections = useMemo(() => (blocks ? headings(blocks).filter((h) => h.level === 2) : []), [blocks]);
  const repository = index?.repository ?? "";
  const here = (doc: string, at: string | null): LinkTo => ({
    href: formatPlace({ page: "guide", doc, ...(at ? { at } : {}) }),
    go: () => {
      onGo(doc, at);
      if (doc === id) show(at); // already its address, perhaps: go there all the same
    },
  });
  const link = (href: string): LinkTo => {
    if (!current) return { href };
    const target = resolveLink(current.path, href, documents, repository);
    if (target.kind === "here") return here(current.id, target.at || null);
    if (target.kind === "doc") return here(target.doc, target.at);
    return { href: target.url };
  };
  const picture = (src: string) => {
    const file = current ? resolvePicture(current.path, src) : null;
    return file ? api.guidePictureUrl(file) : src;
  };

  return (
    <div className="guide" data-testid="guide-page">
      <nav className="guide-nav" aria-label="vexsim's guides">
        <h1>Guide</h1>
        {index && !index.available && (
          <p className="muted small" data-testid="guide-elsewhere">
            vexsim's guides aren't installed beside this copy of it (they come with a clone of its repository). Each of these opens on the repository's pages.
          </p>
        )}
        <ul className="guide-docs" data-testid="guide-docs">
          {documents.map((d) => {
            const to: LinkTo = available ? here(d.id, null) : { href: `${repository}/blob/main/${d.path}` };
            const on = available && d.id === id;
            return (
              <li key={d.id}>
                <a
                  href={to.href}
                  className={on ? "on" : undefined}
                  aria-current={on ? "page" : undefined}
                  {...(to.go ? {} : { target: "_blank", rel: "noreferrer noopener" })}
                  onClick={(event) => {
                    if (!to.go || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
                    event.preventDefault();
                    to.go();
                  }}
                  data-testid={`guide-doc-${d.id}`}
                >
                  <b>{d.title}</b>
                  <span className="muted small">{d.about}</span>
                </a>
                {on && sections.length > 0 && (
                  <ul className="guide-sections" data-testid="guide-sections">
                    {sections.map((section) => {
                      const at = here(d.id, section.id);
                      return (
                        <li key={section.id}>
                          <a
                            href={at.href}
                            className={props.at === section.id ? "on" : undefined}
                            onClick={(event) => {
                              if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
                              event.preventDefault();
                              at.go?.();
                            }}
                          >
                            {section.text}
                          </a>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="guide-body" ref={body} tabIndex={-1}>
        {problem && (
          <p className="problem" role="alert">
            Couldn't read the guide: {problem}
          </p>
        )}
        {available && current && (
          <article className="document" data-testid="guide-document" data-doc={current.id} aria-busy={!blocks}>
            {blocks ? <Markdown blocks={blocks} prefix={PREFIX} link={link} picture={picture} /> : !problem && <p className="muted">Opening {current.title}…</p>}
          </article>
        )}
      </div>
    </div>
  );
}
