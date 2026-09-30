// Render $...$ / $$...$$ maths (pymdownx.arithmatex, generic mode) with KaTeX,
// also after navigation.instant swaps the page.
document$.subscribe(() => {
  renderMathInElement(document.body, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
  });
});
