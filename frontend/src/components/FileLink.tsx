import type { ReactNode } from "react";
import { embedded, saveServerFile } from "../host";

/** A link that downloads one of the server's files; inside VS Code, saved through its save
 * dialog. */
export function FileLink(props: { href: string; name: string; className: string; title?: string; testid?: string; children: ReactNode }) {
  const save = (event: React.MouseEvent) => {
    event.preventDefault();
    saveServerFile(props.href, props.name).catch((error: unknown) => console.error(error));
  };
  return (
    <a className={props.className} href={props.href} download={props.name} title={props.title} data-testid={props.testid} onClick={embedded ? save : undefined}>
      {props.children}
    </a>
  );
}
