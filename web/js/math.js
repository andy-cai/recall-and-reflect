// Math rendering for $...$ (inline) and $$...$$ (display) spans.
//
// Uses locally-vendored KaTeX when present (web/vendor/katex/ — run
// tools/get_katex.py once on a machine with internet to fetch it; nothing is
// ever loaded from a CDN). Without KaTeX the TeX source is shown in a styled
// span, so cards stay readable either way.

(function loadLocalKatex() {
  if (window.katex) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/vendor/katex/katex.min.css';
  link.onerror = () => link.remove();
  const script = document.createElement('script');
  script.src = '/vendor/katex/katex.min.js';
  script.async = true;
  script.onerror = () => script.remove();
  document.head.append(link, script);
})();

const RE = /\$\$([^$]+)\$\$|\$([^$\n]+)\$/g;

function mathEl(tex, display) {
  const span = document.createElement('span');
  if (window.katex) {
    try {
      window.katex.render(tex, span, { displayMode: display, throwOnError: false });
      return span;
    } catch { /* fall through to source span */ }
  }
  span.className = 'math-src';
  span.textContent = tex;
  return span;
}

function replaceTextNode(node) {
  const text = node.nodeValue;
  RE.lastIndex = 0;
  let m, last = 0, any = false;
  const frag = document.createDocumentFragment();
  while ((m = RE.exec(text))) {
    any = true;
    if (m.index > last) frag.append(text.slice(last, m.index));
    frag.append(mathEl((m[1] ?? m[2]).trim(), m[1] !== undefined));
    last = m.index + m[0].length;
  }
  if (!any) return;
  if (last < text.length) frag.append(text.slice(last));
  node.replaceWith(frag);
}

export function renderMathIn(root) {
  if (!root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      /\$[^$\s]/.test(n.nodeValue || '') &&
      !n.parentElement?.closest('.katex, .math-src, textarea, input, script, style')
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(replaceTextNode);
}
