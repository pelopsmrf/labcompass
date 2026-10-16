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

fs.writeFileSync(path.join(dist, "robots.txt"), "User-agent: *\nAllow: /\nSitemap: https://labcompass.ru/sitemap.xml\n");
const today = new Date().toISOString().slice(0, 10);
fs.writeFileSync(path.join(dist, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
  ["https://labcompass.ru/", "https://labcompass.ru/check/", "https://labcompass.ru/vlk/"].map((u) => `  <url><loc>${u}</loc><lastmod>${today}</lastmod></url>`).join("\n") +
  `\n</urlset>\n`);

const left = html.match(/\{\{\w+\}\}/g);
if (left) throw new Error("Не заполнены поля: " + [...new Set(left)].join(", "));
console.log("Готово: dist/ (" + fs.readdirSync(dist).join(", ") + ")");
