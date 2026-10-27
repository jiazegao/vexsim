import { defaultKeymap, history, historyKeymap, indentWithTab, redo, undo } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language";
import type { Diagnostic } from "@codemirror/lint";
import { lintGutter, lintKeymap, setDiagnostics } from "@codemirror/lint";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { EditorSelection, EditorState } from "@codemirror/state";
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import type { Ref } from "react";
import { useEffect, useImperativeHandle, useRef } from "react";
import { spanRange, textChange } from "../configdoc";
import type { PlacedIssue } from "../protocol";

export interface YamlEditorHandle {
  /** Replace the text as one change, undoable like typing. */
  replace(text: string): void;
  /** Select from..to (offsets) and scroll it into view. */
  select(from: number, to: number): void;
  undo(): void;
  redo(): void;
  focus(): void;
}

// Syntax colors from the page's tokens (styles.css), so they follow the theme
const highlight = HighlightStyle.define([
  { tag: tags.comment, color: "var(--syntax-comment)", fontStyle: "italic" },
  { tag: tags.definition(tags.propertyName), color: "var(--syntax-key)" },
  { tag: [tags.content, tags.attributeValue], color: "var(--syntax-value)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-string)" },
  { tag: [tags.labelName, tags.typeName, tags.keyword, tags.meta], color: "var(--syntax-anchor)" },
  { tag: [tags.separator, tags.punctuation, tags.squareBracket, tags.brace], color: "var(--text-secondary)" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "12.5px", backgroundColor: "var(--surface-1)", color: "var(--text-primary)" },
  ".cm-scroller": { fontFamily: "var(--mono)", lineHeight: "1.5" },
  ".cm-content": { caretColor: "var(--text-primary)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--text-primary)" },
  ".cm-gutters": { backgroundColor: "var(--surface-2)", color: "var(--text-muted)", borderRight: "1px solid var(--border)" },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--focus) 6%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--surface-3)", color: "var(--text-secondary)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground": {
    backgroundColor: "color-mix(in srgb, var(--focus) 26%, transparent)",
  },
  ".cm-selectionMatch": { backgroundColor: "color-mix(in srgb, var(--focus) 12%, transparent)" },
  ".cm-tooltip": { backgroundColor: "var(--surface-1)", color: "var(--text-primary)", border: "1px solid var(--border)" },
  ".cm-panels": { backgroundColor: "var(--surface-2)", color: "var(--text-primary)" },
  ".cm-foldPlaceholder": { backgroundColor: "var(--surface-3)", border: "none", color: "var(--text-secondary)" },
});

/** A YAML editor (CodeMirror) showing a config's issues at their lines. */
export function YamlEditor(props: {
  ref?: Ref<YamlEditorHandle>;
  initial: string;
  issues: { text: string; issues: PlacedIssue[] } | null; // the issues of this text
  onChange: (text: string) => void;
  onCursor: (line: number) => void;
  onSave: () => void;
  label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;

  useEffect(() => {
    const editor = new EditorView({
      parent: box.current!,
      state: EditorState.create({
        doc: props.initial,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightSpecialChars(),
          history(),
          foldGutter(),
          drawSelection(),
          indentOnInput(),
          bracketMatching(),
          highlightActiveLine(),
          highlightSelectionMatches(),
          lintGutter(),
          yaml(),
          syntaxHighlighting(highlight),
          EditorState.tabSize.of(2),
          indentUnit.of("  "), // YAML indents with spaces, never tabs
          keymap.of([
            {
              key: "Mod-s",
              preventDefault: true,
              run: () => {
                callbacks.current.onSave();
                return true;
              },
            },
            ...defaultKeymap,
            ...historyKeymap,
            ...foldKeymap,
            ...searchKeymap,
            ...lintKeymap,
            indentWithTab,
          ]),
          theme,
          EditorView.lineWrapping, // a half-width pane: long flow mappings wrap rather than scroll
          EditorView.contentAttributes.of({ "aria-label": props.label }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callbacks.current.onChange(update.state.doc.toString());
            if (update.docChanged || update.selectionSet) {
              callbacks.current.onCursor(update.state.doc.lineAt(update.state.selection.main.head).number);
            }
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // made once: later text comes in through replace()
  }, []);

  useImperativeHandle(
    props.ref,
    () => ({
      replace(text: string) {
        const editor = view.current;
        if (!editor) return;
        const change = textChange(editor.state.doc.toString(), text);
        if (change) editor.dispatch({ changes: change, userEvent: "input.diagram" });
      },
      select(from: number, to: number) {
        const editor = view.current;
        if (!editor) return;
        const length = editor.state.doc.length;
        const range = EditorSelection.range(Math.min(from, length), Math.min(to, length));
        editor.dispatch({ selection: range, effects: EditorView.scrollIntoView(range, { y: "center" }) });
      },
      undo: () => void (view.current && undo(view.current)),
      redo: () => void (view.current && redo(view.current)),
      focus: () => view.current?.focus(),
    }),
    [],
  );

  // the issues, once they're of the text that's in the editor
  useEffect(() => {
    const editor = view.current;
    const found = props.issues;
    if (!editor || !found || editor.state.doc.toString() !== found.text) return;
    const diagnostics: Diagnostic[] = found.issues
      .filter((issue) => issue.span)
      .map((issue) => {
        const { from, to } = spanRange(found.text, issue.span!);
        return {
          from,
          to,
          severity: issue.severity,
          message: issue.location ? `${issue.location}: ${issue.message}` : issue.message,
        };
      });
    editor.dispatch(setDiagnostics(editor.state, diagnostics));
  }, [props.issues]);

  return <div className="yaml-editor" ref={box} data-testid="yaml-editor" />;
}
