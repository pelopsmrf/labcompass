// Сборка в один файл dist/labcompass-vlk.html: его можно открыть двойным щелчком, отправить по почте
// или выложить на любой хостинг. Запуск: node build.js
const fs = require("fs");
const path = require("path");
const src = (f) => path.join(__dirname, "src", f);

const example = fs.readFileSync(path.join(__dirname, "../vlk_calc/example.csv"), "utf8").replace(/^﻿/, "");
fs.writeFileSync(src("example.js"), `// Пример данных (сгенерировано build.js из vlk_calc/example.csv)\nconst EXAMPLE_CSV = ${JSON.stringify(example)};\n`);

let html = fs.readFileSync(src("index.html"), "utf8")
  .replace('<link rel="stylesheet" href="style.css">', () => `<style>\n${fs.readFileSync(src("style.css"), "utf8")}</style>`)
  .replace(/<script src="([\w.-]+)"><\/script>/g, (_, f) => `<script>\n${fs.readFileSync(src(f), "utf8")}</script>`);

fs.mkdirSync(path.join(__dirname, "dist"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "dist", "labcompass-vlk.html"), html);
console.log(`dist/labcompass-vlk.html: ${(html.length / 1024).toFixed(0)} КБ`);
