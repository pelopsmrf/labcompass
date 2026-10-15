// Тесты расчётов: те же случаи, что в vlk_calc/test_vlk.py, плюс сверка с Python на example.csv.
// Запуск: node --test test/
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const VLK = require("../src/vlk-core.js");

const P = { sigma_r: "4", sigma_R: "6", useLab: true, delta_lab: "12,6" };
const close = (a, b, eps = 1e-3) => assert.ok(Math.abs(a - b) < eps, `${a} ≠ ${b}`);

test("повторяемость", () => {
  const c = VLK.evaluate({ kind: "повт", x1: "1,32", x2: "1,25" }, P);
  close(c.value, 0.07); close(c.rel, 5.447); assert.ok(c.ok);
});

test("точность по ОК", () => {
  const c = VLK.evaluate({ kind: "ок", x1: "2,11", c: "2,00" }, P);
  close(c.value, 0.11); close(c.norm, 0.252); assert.ok(c.ok);
  assert.strictEqual(VLK.evaluate({ kind: "ок", x1: "2,30", c: "2,00" }, P).ok, false);
});

test("метод добавок", () => {
  const c = VLK.evaluate({ kind: "доб", x1: "1,285", xd1: "3,20", c: "2,00" }, P);
  close(c.value, 0.085); close(c.norm, 0.434); assert.ok(c.ok);
});

test("Δл = 0,84·Δ", () => {
  assert.strictEqual(VLK.deltaLab({ delta: "15" }), 0.84 * 15);
});

test("ошибки ввода", () => {
  assert.strictEqual(VLK.evaluate({ kind: "", x1: "" }, P), null);
  assert.match(VLK.evaluate({ kind: "повт", x1: "1,2" }, P).error, /X₂/);
  assert.match(VLK.evaluate({ kind: "повт", x1: "abc", x2: "1" }, P).error, /не число/);
  assert.match(VLK.evaluate({ kind: "ок", x1: "1", c: "1" }, { sigma_r: "4" }).error, /Δ/);
});

test("распознавание вида контроля", () => {
  for (const [s, k] of [["повт", "повт"], ["Повторяемость", "повт"], ["ок", "ок"], ["Точность (ОК)", "ок"],
    ["доб", "доб"], ["Точность (добавки)", "доб"], ["прец", "прец"], ["Внутрилаб. прецизионность", "прец"], ["xyz", ""]]) {
    assert.strictEqual(VLK.normKind(s), k, s);
  }
});

test("признаки нарушения стабильности", () => {
  const L = { cl: 4.5, warn: 11.3, action: 14.7, twoSided: false };
  assert.deepStrictEqual(VLK.findSignals([3, 6, 2, 12, 5, 1, 7, 4], L), {});
  assert.ok(VLK.findSignals([3, 5, 15, 2], L)[3]);
  assert.ok(VLK.findSignals([3, 12, 5, 12.5, 2], L)[4]);
  assert.deepStrictEqual(VLK.findSignals([12, 2, -12], { ...L, twoSided: true }), {});
  assert.ok(VLK.findSignals([5, 6, 7, 5, 6, 8, 5, 6, 7], L)[9]);
  assert.ok(VLK.findSignals([1, 2, 3, 4, 5, 6], L)[6]);
});

test("CSV: чтение и запись туда-обратно", () => {
  const rows = VLK.rowsFromTable(VLK.parseTable("дата;вид;x1;x2;c;xd1;xd2\n01.09.2026;повт;1,2;1,3;;;"));
  assert.deepStrictEqual(rows[0], { date: "01.09.2026", kind: "повт", x1: "1,2", x2: "1,3", c: "", xd1: "", xd2: "" });
  assert.deepStrictEqual(VLK.rowsFromTable(VLK.parseTable(VLK.toCSV(rows))), rows);
  // вставка из Excel без заголовка, через табуляцию
  const pasted = VLK.rowsFromTable(VLK.parseTable("02.09.2026\tок\t2,1\t2,08\t2,00"));
  assert.strictEqual(pasted[0].c, "2,00");
});

test("совпадение с vlk.py на example.csv", () => {
  const csvPath = path.join(__dirname, "../../vlk_calc/example.csv");
  const rows = VLK.rowsFromTable(VLK.parseTable(fs.readFileSync(csvPath, "utf8")));
  const params = { sigma_r: "4", sigma_R: "6", delta: "15" };
  const js = rows.map((r) => VLK.evaluate(r, params));

  const py = JSON.parse(execFileSync("python3", ["-c", `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "../../vlk_calc"))})
from vlk import Params, evaluate, read_rows
p = Params("x", "x", 4, 6, 0.84 * 15)
print(json.dumps([[c.value, c.norm, c.rel, c.ok] for c in
    (evaluate(r, i, p) for i, r in enumerate(read_rows(${JSON.stringify(csvPath)}), 1))]))
`]).toString());

  assert.strictEqual(js.length, py.length);
  js.forEach((c, i) => {
    close(c.value, py[i][0], 1e-9); close(c.norm, py[i][1], 1e-9); close(c.rel, py[i][2], 1e-9);
    assert.strictEqual(c.ok, py[i][3]);
  });
});
