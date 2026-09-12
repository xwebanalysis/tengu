/**
 * Locate a finding snippet inside the pretty-printed HTML source.
 *
 * The backend pretty-prints the page (`html_pretty`) and emits it through the
 * `log` event, so every element has its own line. Findings only carry a raw
 * snippet; matching by tag name + key attribute values is the pragmatic way to
 * point at the offending line.
 */

export function htmlLines(html: string): string[] {
  return html ? html.split('\n') : [];
}

export function snippetKeys(snippet: string): string[] {
  const keys: string[] = [];
  const attrRx = /(?:src|href|id|name|for|alt|aria-label|title)=["']([^"']+?)["']/g;
  let match: RegExpExecArray | null;
  while ((match = attrRx.exec(snippet)) !== null) {
    if (match[1]) {
      keys.push(match[1]);
    }
  }
  return keys;
}

export function snippetTag(snippet: string): string | null {
  const match = snippet.match(/<([a-zA-Z][\w-]*)/);
  return match ? match[1].toLowerCase() : null;
}

const normalize = (text: string): string => text.replace(/\s+/g, ' ').trim();

/** 1-based line number of the finding inside `lines`, or -1 when not found. */
export function locateLine(lines: readonly string[], snippet?: string): number {
  if (!snippet || lines.length === 0) {
    return -1;
  }
  const tag = snippetTag(snippet);
  const keys = snippetKeys(snippet);
  const normalizedSnippet = normalize(snippet);

  if (tag) {
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      if (!line.includes(`<${tag}`)) {
        continue;
      }
      if (keys.some((key) => line.includes(key))) {
        return index + 1;
      }
      if (normalizedSnippet && normalize(line).includes(normalizedSnippet.slice(0, 80))) {
        return index + 1;
      }
    }
    for (let index = 0; index < lines.length; index++) {
      if (lines[index].includes(`<${tag}`)) {
        return index + 1;
      }
    }
  }

  for (let index = 0; index < lines.length; index++) {
    if (normalizedSnippet && normalize(lines[index]).includes(normalizedSnippet.slice(0, 100))) {
      return index + 1;
    }
  }

  return -1;
}

/** True when the source line matches the snippet (used for highlighting). */
export function lineMatchesSnippet(line: string, snippet?: string): boolean {
  if (!line || !snippet) {
    return false;
  }
  const tag = snippetTag(snippet);
  if (tag && !line.includes(`<${tag}`) && !line.includes(`</${tag}>`)) {
    return false;
  }
  const keys = snippetKeys(snippet);
  if (keys.length > 0 && keys.some((key) => line.includes(key))) {
    return true;
  }
  if (line.includes(snippet.slice(0, 80))) {
    return true;
  }
  const normalizedLine = normalize(line);
  const normalizedSnippet = normalize(snippet);
  return normalizedSnippet.length > 0 && normalizedLine.includes(normalizedSnippet.slice(0, 100));
}

/** Escape HTML and wrap tags/attributes/values in syntax highlight spans. */
export function highlightHtmlLine(line: string): string {
  const escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped
    .replace(/(&lt;\/?)([a-zA-Z][\w-]*)/g, '<span class="syn-tag">$1$2</span>')
    .replace(
      /\b((?:src|href|class|id|name|rel|type|alt|title|width|height|lang|charset|content|property|http-equiv|media|style|integrity|crossorigin|as|hreflang|fetchPriority|noModule|aria-label|aria-current|aria-expanded|aria-controls|aria-busy|aria-live|aria-hidden|aria-describedby|aria-labelledby|target|rel|sizes))\s*=\s*/g,
      '<span class="syn-attr">$1</span>=',
    )
    .replace(/=("(?:[^"\\]|\\.)*")/g, '=<span class="syn-val">$1</span>')
    .replace(/(&lt;\/)([a-zA-Z][\w-]*)(&gt;)/g, '<span class="syn-tag">$1$2</span>$3')
    .replace(/(&lt;)([a-zA-Z][\w-]*)/g, '<span class="syn-tag">$1$2</span>')
    .replace(/(\/?&gt;)/g, '<span class="syn-punc">$1</span>');
}
