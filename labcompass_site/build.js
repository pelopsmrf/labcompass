// Сборка сайта в dist/: подставляет контакты из config.json и кладёт калькулятор в dist/vlk/.
// Запуск: node build.js   Затем загрузите содержимое dist/ на хостинг.
const fs = require("fs");
const path = require("path");
const here = (...p) => path.join(__dirname, ...p);
const cfg = JSON.parse(fs.readFileSync(here("config.json"), "utf8"));
const tg = (cfg.telegram || "").replace(/^@/, "").trim();

const dist = here("dist");
fs.rmSync(dist, { recursive: true, force: true });
fs.cpSync(here("src"), dist, { recursive: true });

let html = fs.readFileSync(path.join(dist, "index.html"), "utf8")
  .replaceAll("{{EMAIL}}", cfg.email)
  .replaceAll("{{YEAR}}", String(new Date().getFullYear()));
html = tg ? html.replaceAll("{{TELEGRAM}}", tg) : html.replace(/<!--TG-->[\s\S]*?<!--\/TG-->/g, "");
fs.writeFileSync(path.join(dist, "index.html"), html);

// Калькулятор: собираем свежую версию и кладём в /vlk/
const vlk = here("../vlk_web");
require("child_process").execFileSync("node", [path.join(vlk, "build.js")], { stdio: "ignore" });
fs.mkdirSync(path.join(dist, "vlk"), { recursive: true });
fs.copyFileSync(path.join(vlk, "dist", "labcompass-vlk.html"), path.join(dist, "vlk", "index.html"));

// Статьи из articles/*.md
const cssV = "/style.css?v=" + require("crypto").createHash("md5").update(fs.readFileSync(here("src", "style.css"))).digest("hex").slice(0, 8);
const articleUrls = require("./articles.js")(here("articles"), path.join(dist, "articles"), cssV);

fs.writeFileSync(path.join(dist, "robots.txt"), "User-agent: *\nAllow: /\nSitemap: https://labcompass.ru/sitemap.xml\n");
const today = new Date().toISOString().slice(0, 10);
fs.writeFileSync(path.join(dist, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
  ["/", "/check/", "/vlk/", ...articleUrls].map((u) => "https://labcompass.ru" + u).map((u) => `  <url><loc>${u}</loc><lastmod>${today}</lastmod></url>`).join("\n") +
  `\n</urlset>\n`);

// Яндекс Метрика (номер счётчика в config.json → metrika). Вебвизор выключен: данные лабораторий не записываем.
const metrika = String(cfg.metrika || "").trim();
const verify = String(cfg.yandex_verification || "").trim();
const counter = metrika ? `<script>window.LC_METRIKA=${Number(metrika)};
(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();
k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");
ym(${Number(metrika)},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true});</script>
<div class="lc-cookie" id="lcCookie" hidden>Сайт использует cookie и Яндекс Метрику для статистики посещений. <a href="/app/privacy">Подробнее</a> <button type="button" onclick="localStorage.setItem('lcCookie','1');this.parentNode.hidden=true">Понятно</button></div>
<script>if(!localStorage.getItem("lcCookie"))document.getElementById("lcCookie").hidden=false;</script>
<style>.lc-cookie{position:fixed;left:12px;right:12px;bottom:12px;max-width:560px;margin:0 auto;background:#1f2933;color:#fff;font:14px/1.4 system-ui,sans-serif;padding:10px 14px;border-radius:10px;z-index:50;display:flex;gap:10px;align-items:center;flex-wrap:wrap}.lc-cookie[hidden]{display:none}.lc-cookie a{color:#cfe0f0}.lc-cookie button{margin-left:auto;background:#fff;color:#1f2933;border:0;border-radius:6px;padding:5px 12px;font:inherit;cursor:pointer}</style>
` : "";
if (metrika && !/^\d+$/.test(metrika)) throw new Error("metrika в config.json — только цифры номера счётчика");
const allHtml = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? allHtml(path.join(dir, e.name)) : e.name.endsWith(".html") ? [path.join(dir, e.name)] : []);
for (const f of allHtml(dist)) {
  // Версия в адресе style.css: после обновления браузер не возьмёт старое оформление из кэша
  let h = fs.readFileSync(f, "utf8").replace(/href="(?:\.\.\/|\/)?style\.css"/g, `href="${cssV}"`);
  if (counter) h = h.replace("</body>", counter + "</body>");
  if (verify && f === path.join(dist, "index.html"))
    h = h.replace("</head>", `<meta name="yandex-verification" content="${verify.replace(/[^\w-]/g, "")}">\n</head>`);
  fs.writeFileSync(f, h);
}
html = fs.readFileSync(path.join(dist, "index.html"), "utf8");

const left = html.match(/\{\{\w+\}\}/g);
if (left) throw new Error("Не заполнены поля: " + [...new Set(left)].join(", "));
console.log("Готово: dist/ (" + fs.readdirSync(dist).join(", ") + ")");
