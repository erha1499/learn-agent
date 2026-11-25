// 一次只显示一个单元（导读也算一个），地址栏的 #id 决定显示哪个、滚到哪。
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const body = document.body;
  const units = $$("article.unit");
  const toc = $(".toc"), results = $(".results"), q = $("#q");
  const barTitle = $(".bar-title");
  const SPY = 96;                      // 标题滚到离顶部这么近，就算读到了这一节
  let current = null, spyId = null, pin = null;

  try { history.scrollRestoration = "manual"; } catch (e) {}

  const decode = (h) => { try { return decodeURIComponent(h); } catch (e) { return h; } };
  const escHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  /* 深浅色 */
  function toggleTheme() {
    const now = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    root.dataset.theme = now === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  }
  $$(".theme").forEach((b) => b.addEventListener("click", toggleTheme));

  /* 路由 */
  function target(hash) {
    const id = decode((hash || "").replace(/^#/, ""));
    return (id && document.getElementById(id)) || units[0];
  }

  function show(el) {
    const art = el.closest("article.unit") || units[0];
    if (art !== current) {
      if (current) current.classList.remove("on");
      art.classList.add("on");
      current = art;
      const uid = art.dataset.unit, label = art.dataset.label;
      $$(".toc .u").forEach((a) => a.classList.toggle("on", a.dataset.unit === uid));
      $$(".toc .secs").forEach((o) => o.classList.toggle("on", o.dataset.unit === uid));
      document.title = uid === "guide" ? "learn-agent" : `${label} · learn-agent`;
      barTitle.textContent = uid === "guide" ? "learn-agent" : label;
      revealInNav();
    }
    for (let d = el.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    if (el === art || el.tagName === "H1" || el.classList.contains("part-intro")) scrollTo(0, 0);
    else el.scrollIntoView();
    pin = /^H[23]$/.test(el.tagName) && el.id ? { el, y: scrollY } : null;
    spyId = null;
    spy();
  }

  function go(hash, el) {
    if (decode(location.hash) !== decode(hash)) history.pushState(null, "", hash);
    show(el || target(hash));
    closeNav();
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go(a.getAttribute("href"), hitTarget.get(a));
    if (hitTarget.has(a)) flash(hitTarget.get(a));
  });
  addEventListener("popstate", () => { show(target(location.hash)); closeNav(); });

  /* 读到哪一节：高亮导航，地址栏跟着改，刷新后回到原处。
     跳到页尾的短小节时它滚不到顶部，所以跳转的目标先钉住，用户自己滚了再按位置算。 */
  function spy() {
    if (!current) return;
    const heads = [...current.querySelectorAll("h2[id],h3[id]")];
    let k = -1;
    if (pin && Math.abs(scrollY - pin.y) < 4) k = heads.indexOf(pin.el);
    else {
      pin = null;
      while (k + 1 < heads.length && heads[k + 1].getBoundingClientRect().top <= SPY) k++;
    }
    const head = heads[k];
    let j = k;
    while (j >= 0 && heads[j].tagName !== "H2") j--;
    const h2 = heads[j];
    const id = head ? head.id : current.dataset.unit;
    if (id === spyId) return;
    spyId = id;
    history.replaceState(null, "", "#" + id);
    const href = h2 ? "#" + h2.id : "";
    $$(".secs.on a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === href));
  }
  let ticking = false;
  addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { ticking = false; spy(); });
  }, { passive: true });

  function revealInNav() {
    const a = $(".toc .u.on");
    if (!a || toc.hidden) return;
    const r = a.getBoundingClientRect(), box = toc.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom - 120) toc.scrollTop += r.top - box.top - 80;
  }

  /* 手机抽屉 */
  function closeNav() { body.classList.remove("nav-open"); }
  $(".menu").addEventListener("click", () => {
    body.classList.toggle("nav-open");
    if (body.classList.contains("nav-open")) revealInNav();
  });
  $(".scrim").addEventListener("click", closeNav);

  /* 搜索：全书按块建索引，几个词都要出现 */
  const hitTarget = new WeakMap();
  let index = null;

  function buildIndex() {
    index = [];
    for (const art of units) {
      let sec = null;
      for (const el of art.querySelectorAll("h1,h2,h3,p,li,th,td,pre,blockquote,summary,.ans")) {
        if (el.matches("ol.quiz>li")) continue;
        if (/^H[123]$/.test(el.tagName)) sec = el;
        const text = el.textContent.replace(/\s+/g, " ").trim();
        if (text) index.push({ el, art, sec, text, low: text.toLowerCase(), head: el === sec });
      }
    }
  }

  function snippet(text, terms) {
    const low = text.toLowerCase();
    const at = Math.max(0, Math.min(...terms.map((t) => low.indexOf(t)).filter((i) => i >= 0)));
    const from = Math.max(0, at - 24), to = Math.min(text.length, at + 90);
    const part = (from ? "…" : "") + text.slice(from, to) + (to < text.length ? "…" : "");
    const re = new RegExp(terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gi");
    let out = "", last = 0;
    part.replace(re, (m, i) => {
      out += escHtml(part.slice(last, i)) + "<mark>" + escHtml(m) + "</mark>";
      last = i + m.length;
      return m;
    });
    return out + escHtml(part.slice(last));
  }

  function search() {
    const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    toc.hidden = !!terms.length;
    results.hidden = !terms.length;
    if (!terms.length) return revealInNav();
    if (!index) buildIndex();
    const match = index.filter((it) => terms.every((t) => it.low.includes(t)));
    const hits = [...match.filter((it) => it.head), ...match.filter((it) => !it.head)].slice(0, 100);
    results.replaceChildren(...hits.map((it) => {
      const a = document.createElement("a");
      a.className = "hit";
      a.href = "#" + (it.sec && it.sec.tagName !== "H1" ? it.sec.id : it.art.dataset.unit);
      const where = it.art.dataset.label + (it.sec && it.sec.tagName !== "H1" && !it.head ? " · " + it.sec.textContent : "");
      a.innerHTML = `<div class="where">${escHtml(where)}</div><div class="snip">${snippet(it.text, terms)}</div>`;
      hitTarget.set(a, it.el);
      return a;
    }));
    if (!hits.length) results.innerHTML = '<div class="none">无结果</div>';
    results.scrollTop = 0;
  }

  function flash(el) {
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }

  let timer;
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 120); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { q.value = ""; search(); q.blur(); }
    if (e.key === "Enter") { clearTimeout(timer); search(); const a = $(".hit", results); if (a) a.click(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
    e.preventDefault();
    if (matchMedia("(max-width: 860px)").matches) body.classList.add("nav-open");
    q.focus();
    q.select();
  });

  /* 代码块的复制按钮 */
  for (const box of $$(".code")) {
    const b = document.createElement("button");
    b.className = "copy";
    b.textContent = "复制";
    b.addEventListener("click", async () => {
      const pre = $("pre", box);
      try {
        await navigator.clipboard.writeText(pre.innerText);
        b.textContent = "已复制";
      } catch (e) {
        getSelection().selectAllChildren(pre);
      }
      setTimeout(() => { b.textContent = "复制"; }, 1500);
    });
    box.append(b);
  }

  show(target(location.hash));
})();
