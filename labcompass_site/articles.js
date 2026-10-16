// Статьи: articles/*.md → dist/articles/<имя>/index.html и список dist/articles/index.html.
// Формат файла: шапка между строками --- (title, description, date), дальше простой Markdown:
// ## заголовки, абзацы, списки «- » и «1. », таблицы | a | b |, **жирный**, *курсив*, [ссылка](адрес).
const fs = require("fs");
const path = require("path");

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const inline = (s) => esc(s)
  .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
  .replace(/\*(.+?)\*/g, "<i>$1</i>")
  .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>');

function markdown(md) {
  const out = [];
  const kind = (l) => /^#{2,3} /.test(l) ? "h" : /^- /.test(l) ? "ul" : /^\d+\. /.test(l) ? "ol" : l.startsWith("|") ? "table" : "p";
  for (const b of md.trim().split(/\n\s*\n/)) {
    // Внутри блока строки группируются по виду: текст, затем список без пустой строки между ними — нормально
    const runs = [];
    for (const l of b.split("\n")) {
      const k = kind(l);
      if (runs.length && runs[runs.length - 1].k === k && k !== "h") runs[runs.length - 1].lines.push(l);
      else runs.push({ k, lines: [l] });
    }
    for (const { k, lines } of runs) {
      if (k === "h") {
        const level = lines[0].startsWith("### ") ? 3 : 2;
        out.push(`<h${level}>${inline(lines[0].replace(/^#+ /, ""))}</h${level}>`);
      } else if (k === "ul") {
        out.push("<ul>" + lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("") + "</ul>");
      } else if (k === "ol") {
        out.push("<ol>" + lines.map((l) => `<li>${inline(l.replace(/^\d+\. /, ""))}</li>`).join("") + "</ol>");
      } else if (k === "table") {
        const cells = (l) => l.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        const [head, , ...rows] = lines;
        out.push(`<div class="tbl"><table><tr>${cells(head).map((c) => `<th>${c}</th>`).join("")}</tr>` +
          rows.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</table></div>");
      } else {
        out.push(`<p>${inline(lines.join(" "))}</p>`);
      }
    }
  }
  return out.join("\n");
}

function parse(file) {
  const text = fs.readFileSync(file, "utf8");
  const m = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) throw new Error("Нет шапки --- в " + file);
  const meta = Object.fromEntries(m[1].split("\n").map((l) => [l.slice(0, l.indexOf(":")).trim(), l.slice(l.indexOf(":") + 1).trim()]));
  for (const k of ["title", "description", "date"]) if (!meta[k]) throw new Error(`Нет поля ${k} в ${file}`);
  return { ...meta, slug: path.basename(file, ".md"), body: markdown(m[2]) };
}

const ruDate = (d) => d.split("-").reverse().join(".");

function layout({ title, description, url, css, main }) {
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} — ЛабКомпас</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="https://labcompass.ru${url}">
<meta property="og:type" content="article">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:image" content="https://labcompass.ru/img/og.png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="${css}">
</head>
<body>
<header class="nav">
  <div class="wrap nav-in">
    <a class="logo" href="/" aria-label="ЛабКомпас — на главную">
      <svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M16 5 L20 16 L16 27 L12 16 Z" fill="currentColor" opacity=".3"/><path d="M16 5 L20 16 L12 16 Z" fill="currentColor"/></svg>
      ЛабКомпас
    </a>
    <nav>
      <a href="/articles/">Статьи</a>
      <a href="/check/">Самопроверка</a>
      <a href="/vlk/">Калькулятор ВЛК</a>
      <a href="/#contact" class="btn small">Связаться</a>
    </nav>
  </div>
</header>
<main class="article">
${main}
</main>
<footer>
  <div class="wrap foot-in">
    <span>ЛабКомпас · labcompass.ru</span>
    <span>Независимый консультант. Не является органом по аккредитации.</span>
  </div>
</footer>
</body>
</html>
`;
}

// Собирает статьи; возвращает адреса страниц для sitemap
module.exports = function buildArticles(srcDir, distDir, css) {
  const list = fs.readdirSync(srcDir).filter((f) => f.endsWith(".md")).sort()
    .map((f) => parse(path.join(srcDir, f)))
    .sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title));
  const urls = ["/articles/"];
  for (const a of list) {
    const url = `/articles/${a.slug}/`;
    urls.push(url);
    fs.mkdirSync(path.join(distDir, a.slug), { recursive: true });
    fs.writeFileSync(path.join(distDir, a.slug, "index.html"), layout({
      title: a.title, description: a.description, url, css,
      main: `<article class="wrap narrow">
<p class="crumbs"><a href="/articles/">Статьи</a> · ${ruDate(a.date)}</p>
<h1>${esc(a.title)}</h1>
${a.body}
<div class="art-cta"><b>Готовитесь к экспертизе?</b> Пройдите бесплатную <a href="/check/">самопроверку готовности</a> или <a href="/#contact">опишите задачу</a> — ответим в течение рабочего дня.</div>
</article>`,
    }));
  }
  fs.writeFileSync(path.join(distDir, "index.html"), layout({
    title: "Статьи об аккредитации лабораторий", url: "/articles/", css,
    description: "Практические статьи о подготовке испытательных лабораторий к аккредитации и подтверждению компетентности: ВЛК, оборудование, типичные замечания экспертов.",
    main: `<div class="wrap narrow">
<h1>Статьи</h1>
<p class="lead">Практика подготовки лабораторий к аккредитации и подтверждению компетентности.</p>
${list.map((a) => `<a class="art-item" href="/articles/${a.slug}/"><b>${esc(a.title)}</b><span>${esc(a.description)}</span></a>`).join("\n")}
</div>`,
  }));
  return urls;
};
