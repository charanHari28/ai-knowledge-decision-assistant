/* Embeddable assistant. Usage on any website:
 *   <script src="https://YOUR-HOST/embed.js" data-assistant="ast_..." async></script>
 * Adds a floating button that opens the organization's assistant in an iframe.
 * Optional attributes: data-position="left", data-label="Ask us".
 */
(function () {
  var script = document.currentScript || document.querySelector("script[data-assistant]");
  if (!script) return;
  var token = script.getAttribute("data-assistant");
  if (!token) { console.warn("[assistant] data-assistant token missing"); return; }
  var host = new URL(script.src).origin;
  var left = script.getAttribute("data-position") === "left";
  var label = script.getAttribute("data-label") || "Ask a question";
  var side = left ? "left:20px;" : "right:20px;";

  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-label", label);
  btn.style.cssText = "position:fixed;bottom:20px;" + side + "z-index:2147483646;display:flex;align-items:center;gap:8px;" +
    "background:#17233b;color:#fff;border:0;border-radius:999px;padding:12px 18px 12px 14px;font:600 15px/1 system-ui,sans-serif;" +
    "box-shadow:0 8px 24px rgba(23,35,59,.28);cursor:pointer";
  btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" fill="none" stroke="#7fd1d6" stroke-width="2" stroke-linejoin="round"/></svg><span></span>';
  btn.querySelector("span").textContent = label;

  var panel = document.createElement("div");
  panel.style.cssText = "position:fixed;bottom:84px;" + side + "z-index:2147483647;width:min(400px,calc(100vw - 32px));" +
    "height:min(620px,calc(100vh - 110px));border-radius:16px;overflow:hidden;box-shadow:0 18px 48px rgba(23,35,59,.32);display:none;background:#fff";
  var frame = document.createElement("iframe");
  frame.title = label;
  frame.style.cssText = "width:100%;height:100%;border:0";
  frame.setAttribute("referrerpolicy", "no-referrer");
  panel.appendChild(frame);

  btn.addEventListener("click", function () {
    var open = panel.style.display === "none";
    if (open && !frame.src) frame.src = host + "/a/" + encodeURIComponent(token) + "?embed=1";
    panel.style.display = open ? "block" : "none";
    btn.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.style.display === "block") { panel.style.display = "none"; btn.setAttribute("aria-expanded", "false"); btn.focus(); }
  });

  function mount() { document.body.appendChild(panel); document.body.appendChild(btn); }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
