// The shared element builder. Every served module that constructs DOM imports
// el() from here (the twelve panel/editor modules used to carry byte-identical
// copies). Text is assigned through textContent only, never through
// innerHTML: panels render untrusted marker text written in project files.
export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
