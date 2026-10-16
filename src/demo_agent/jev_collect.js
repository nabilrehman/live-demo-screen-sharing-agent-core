() => {
  document.querySelectorAll('[data-jev-id]').forEach(e => e.removeAttribute('data-jev-id'));
  const SEL = 'a[href],button,input,textarea,select,summary,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="menuitemcheckbox"],[role="menuitemradio"],[role="option"],[role="checkbox"],[role="radio"],[role="switch"],[role="searchbox"],[role="textbox"],[role="combobox"],[role="treeitem"],[contenteditable="true"],[onclick]';
  const out = [];
  let n = 0;
  const vw = window.innerWidth, vh = window.innerHeight;
  const seen = new Set();

  function labelOf(el) {
    const tryAttr = (a) => (el.getAttribute(a) || "").trim();
    const byId = tryAttr("aria-labelledby");
    if (byId) {
      const t = byId.split(/\s+/).map((i) => (el.getRootNode().getElementById?.(i) || document.getElementById(i))?.innerText || "").join(" ").trim();
      if (t) return t;
    }
    // addition to jev-guide: radios/checkboxes without aria-label take the text of their wrapping <label>/card
    function wrapText(e) {
      if (e.tagName !== "INPUT" || !/^(radio|checkbox)$/.test(e.type)) return "";
      let p = e.closest("label") || e.parentElement;
      for (let i = 0; p && i < 4; i++, p = p.parentElement) { const t = (p.innerText || "").trim(); if (t) return t.split("\n").slice(0, 2).join(" - "); }
      return "";
    }
    const cands = [tryAttr("aria-label"), (el.innerText || "").trim(), tryAttr("placeholder"), tryAttr("title"), tryAttr("alt"), wrapText(el), tryAttr("name")];
    if (el.tagName === "INPUT" && ["submit", "button"].includes(el.type)) cands.unshift(el.value || "Submit");
    const img = el.querySelector?.("img[alt], svg[aria-label], [aria-label]");
    if (img) cands.push(img.getAttribute("alt") || img.getAttribute("aria-label") || "");
    if (el.tagName === "INPUT" && el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) cands.push(l.innerText); }
    const t = cands.find((c) => c && c.trim());
    return (t || "").replace(/\s+/g, " ").trim().slice(0, 80);
  }
  function visible(el) {
    if (!el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    return true;
  }
  function kindOf(el) {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute("role") || "").toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "select") return "select";
    if (tag === "textarea" || role === "textbox" || role === "searchbox" || el.isContentEditable) return "text field";
    if (tag === "input") {
      if (["checkbox", "radio"].includes(type)) return type;
      if (["submit", "button", "reset", "image"].includes(type)) return "button";
      if (type === "password") return "password field";
      if (type === "search") return "search box";
      return "text field";
    }
    if (role === "combobox") return "dropdown";
    if (role) return role;
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    return "clickable";
  }
  function walk(root) {
    const nodes = root.querySelectorAll ? root.querySelectorAll("*") : [];
    for (const el of nodes) {
      if (el.shadowRoot) walk(el.shadowRoot);
      if (!el.matches || !el.matches(SEL)) continue;
      if (el.id && (el.id.startsWith("__jev") || el.id.startsWith("__k"))) continue;
      if (seen.has(el)) continue;
      seen.add(el);
      if (!visible(el)) continue;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
      // Skip wrappers whose only purpose is to contain another interactive element.
      const inner = el.querySelector?.(SEL);
      if (inner && el.tagName !== "A" && el.tagName !== "BUTTON" && inner.getBoundingClientRect().width > 0) continue;
      const label = labelOf(el);
      if (!label && !["text field", "search box", "select", "dropdown"].includes(kindOf(el))) continue;
      const r = el.getBoundingClientRect();
      const id = "j" + ++n;
      el.setAttribute("data-jev-id", id);
      const kind = kindOf(el);
      const extra = [];
      if (el.tagName === "A") { const h = el.getAttribute("href") || ""; if (h && !h.startsWith("javascript") && h !== "#") extra.push("href=" + h.slice(0, 60)); }
      if (el.getAttribute("aria-selected") === "true" || el.getAttribute("aria-checked") === "true" || el.checked) extra.push("selected");
      if (el.getAttribute("aria-expanded") === "true") extra.push("expanded");
      if (el.value && ["text field", "search box"].includes(kind)) extra.push("value=" + String(el.value).slice(0, 40));
      out.push({
        id, kind, label,
        extra: extra.join(", "),
        inViewport: r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw,
        top: Math.round(r.top), left: Math.round(r.left), x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2), w: Math.round(r.width), h: Math.round(r.height),
      });
      if (out.length >= 2000) return;
    }
  }
  walk(document);
  return out;
}
