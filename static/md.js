// Tiny, safe markdown renderer for answers: escapes HTML first, then supports
// **bold**, bullet / numbered lists, pipe tables, paragraphs and [n] citation chips.
window.renderMarkdown = function (src) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d{1,2})\]/g, '<span class="cite" title="Source $1">$1</span>');
  const lines = String(src || "").split("\n");
  let html = "", i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*\|.*\|\s*$/.test(line)) {                       // table
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      html += "<table><thead><tr>" + cells(body[0]).map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
        body.slice(1).map((r) => "<tr>" + cells(r).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {                          // bullet list
      html += "<ul>";
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) html += `<li>${inline(lines[i++].replace(/^\s*[-*•]\s+/, ""))}</li>`;
      html += "</ul>";
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {                        // numbered list
      html += "<ol>";
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) html += `<li>${inline(lines[i++].replace(/^\s*\d+[.)]\s+/, ""))}</li>`;
      html += "</ol>";
      continue;
    }
    if (line.trim()) html += `<p>${inline(line)}</p>`;
    i++;
  }
  return html;
};
