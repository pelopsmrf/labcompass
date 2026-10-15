/* Интерфейс калькулятора ВЛК. Расчёты — в vlk-core.js (глобальный объект VLK). */
(function () {
  const STORE = "vlk-web-v1";
  const FIELDS = ["x1", "x2", "c", "xd1", "xd2"];
  const $ = (s) => document.querySelector(s);
  const tbody = $("#grid tbody");

  const emptyRow = () => ({ date: "", kind: "", x1: "", x2: "", c: "", xd1: "", xd2: "" });
  const defaults = () => ({
    params: { name: "", units: "мг/дм³", sigma_r: "", sigma_R: "", delta: "", delta_lab: "", useLab: false },
    rows: Array.from({ length: 5 }, emptyRow),
  });

  let state = load() || defaults();

  // ---------- форматирование ----------
  const fmt = (x) => Number(x.toPrecision(3)).toLocaleString("ru-RU", { maximumFractionDigits: 6 });
  const pct = (x) => x.toFixed(1).replace(".", ",");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------- хранение ----------
  function load() {
    try { return JSON.parse(localStorage.getItem(STORE)); } catch { return null; }
  }
  let saveTimer;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try {
        localStorage.setItem(STORE, JSON.stringify(state));
        $("#saved").textContent = "Данные сохранены в этом браузере.";
      } catch { $("#saved").textContent = "Не удалось сохранить данные в браузере."; }
    }, 300);
  }

  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const fileBase = () => (state.params.name.trim() || "ВЛК").replace(/[\\/:*?"<>|]/g, "_");

  // ---------- параметры ----------
  function renderParams() {
    document.querySelectorAll("[data-p]").forEach((el) => (el.value = state.params[el.dataset.p] ?? ""));
    const lab = !!state.params.useLab;
    document.querySelectorAll("[data-delta]").forEach((b) => b.classList.toggle("on", (b.dataset.delta === "lab") === lab));
    $("#delta-method").hidden = lab;
    $("#delta-lab").hidden = !lab;
    updateDeltaHint();
  }
  function updateDeltaHint() {
    const d = VLK.num(state.params.delta);
    $("#delta-hint").textContent = d > 0 ? `Δл = 0,84·Δ = ${pct(VLK.K.DELTA_LAB_K * d)} %` : "Δл = 0,84·Δ";
    document.querySelectorAll("[data-p]").forEach((el) => {
      const numeric = !["name", "units"].includes(el.dataset.p);
      el.classList.toggle("invalid", numeric && Number.isNaN(VLK.num(el.value)));
    });
  }

  $("#params").addEventListener("input", (e) => {
    const k = e.target.dataset.p;
    if (!k) return;
    state.params[k] = e.target.value;
    updateDeltaHint();
    recalc();
  });
  document.querySelectorAll("[data-delta]").forEach((b) =>
    b.addEventListener("click", () => {
      state.params.useLab = b.dataset.delta === "lab";
      renderParams();
      recalc();
    })
  );

  // ---------- таблица ----------
  const kindOptions = '<option value="">— выберите —</option>' +
    Object.entries(VLK.KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");

  function renderTable() {
    tbody.innerHTML = state.rows.map((r, i) => `
      <tr data-i="${i}">
        <td class="n">${i + 1}</td>
        <td><input data-f="date" value="${esc(r.date)}" placeholder="дд.мм.гггг"></td>
        <td><select data-f="kind">${kindOptions}</select></td>
        ${FIELDS.map((f) => `<td><input data-f="${f}" inputmode="decimal" value="${esc(r[f])}"></td>`).join("")}
        <td class="res value"></td><td class="res norm"></td><td class="verdict"></td>
        <td class="noprint"><button type="button" class="del" title="Удалить строку" aria-label="Удалить строку">✕</button></td>
      </tr>`).join("");
    tbody.querySelectorAll("tr").forEach((tr, i) => {
      tr.querySelector("select").value = state.rows[i].kind;
      updateRowFields(tr, state.rows[i]);
    });
    recalc();
  }

  function updateRowFields(tr, row) {
    const allowed = row.kind ? VLK.FIELDS[row.kind] : FIELDS;
    FIELDS.forEach((f) => {
      const el = tr.querySelector(`[data-f="${f}"]`);
      el.disabled = !allowed.includes(f);
      el.placeholder = el.disabled ? "—" : "";
    });
  }

  tbody.addEventListener("input", (e) => {
    const f = e.target.dataset.f;
    if (!f) return;
    const tr = e.target.closest("tr");
    const row = state.rows[tr.dataset.i];
    row[f] = e.target.value;
    if (f === "kind") updateRowFields(tr, row);
    recalc();
  });

  tbody.addEventListener("click", (e) => {
    if (!e.target.classList.contains("del")) return;
    state.rows.splice(e.target.closest("tr").dataset.i, 1);
    if (!state.rows.length) state.rows.push(emptyRow());
    renderTable();
  });

  // Enter — на строку ниже (как в Excel), с добавлением строки в конце таблицы
  tbody.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.dataset.f) return;
    e.preventDefault();
    const i = +e.target.closest("tr").dataset.i;
    const f = e.target.dataset.f;
    if (i === state.rows.length - 1) {
      state.rows.push(emptyRow());
      renderTable();
    }
    focusCell(i + 1, f);
  });

  function focusCell(i, f) {
    const el = tbody.querySelector(`tr[data-i="${i}"] [data-f="${f}"]`);
    if (el) el.focus();
  }

  // Вставка блока из Excel начиная с ячейки под курсором
  tbody.addEventListener("paste", (e) => {
    const f = e.target.dataset.f;
    const text = (e.clipboardData || window.clipboardData).getData("text");
    if (!f || !/[\t\n]/.test(text.trim())) return; // одиночное значение — обычная вставка
    e.preventDefault();
    let cells = VLK.parseTable(text, "\t");
    if (cells.length && /дата|вид/i.test(cells[0].join(" "))) cells = cells.slice(1);
    const startRow = +e.target.closest("tr").dataset.i;
    const startCol = VLK.COLUMNS.indexOf(f);
    cells.forEach((line, j) => {
      const i = startRow + j;
      while (state.rows.length <= i) state.rows.push(emptyRow());
      line.forEach((val, k) => {
        const col = VLK.COLUMNS[startCol + k];
        if (col) state.rows[i][col] = col === "kind" ? VLK.normKind(val) : val;
      });
    });
    renderTable();
    focusCell(startRow, f);
  });

  // ---------- расчёт и вывод ----------
  function recalc() {
    const results = state.rows.map((r) => VLK.evaluate(r, state.params));
    tbody.querySelectorAll("tr").forEach((tr, i) => {
      const r = results[i];
      const [value, norm, verdict] = [".value", ".norm", ".verdict"].map((s) => tr.querySelector(s));
      tr.classList.toggle("bad", !!(r && !r.error && !r.ok));
      tr.classList.toggle("empty", !r);
      if (!r) { value.textContent = norm.textContent = verdict.textContent = ""; return; }
      if (r.error) {
        value.textContent = norm.textContent = "";
        verdict.innerHTML = `<span class="v-err">${esc(r.error)}</span>`;
        return;
      }
      value.textContent = fmt(r.value);
      norm.textContent = "≤ " + fmt(r.norm);
      verdict.innerHTML = r.ok ? '<span class="v-ok">✓ удовл.</span>' : '<span class="v-bad">✗ не удовл.</span>';
    });
    renderResults(results);
    save();
  }

  function renderResults(results) {
    const valid = results.map((r, i) => ({ ...r, row: i + 1, date: state.rows[i].date })).filter((r) => r.kind && !r.error && r.value !== undefined);
    const errors = results.filter((r) => r && r.error).length;
    const failed = valid.filter((r) => !r.ok);
    let signalCount = 0;

    const blocks = Object.keys(VLK.KINDS).map((kind) => {
      const items = valid.filter((r) => r.kind === kind);
      if (!items.length) return "";
      const lim = VLK.chartLimits(kind, state.params);
      const bad = items.filter((r) => !r.ok).length;
      let body;
      if (items.length < 3) {
        body = `<p class="few">Для контрольной карты нужно не менее 3 точек (сейчас ${items.length}).</p>`;
      } else {
        const sig = VLK.findSignals(items.map((r) => r.rel), lim);
        signalCount += Object.keys(sig).length;
        body = chartSVG(items, lim, sig) + legend(lim, bad > 0) + signalList(items, sig);
      }
      return `<div class="chart-block">
        <h3>${VLK.KINDS[kind]}</h3>
        <div class="meta">Процедур: ${items.length} · неудовлетворительных: ${bad} ·
          средняя линия ${pct(lim.cl)} %, ПП ${lim.twoSided ? "±" : ""}${pct(lim.warn)} %, ПД ${lim.twoSided ? "±" : ""}${pct(lim.action)} %</div>
        ${body}</div>`;
    }).join("");

    let banner;
    if (!valid.length) {
      banner = `<div class="banner empty">Заполните параметры методики и результаты контроля — итоги и контрольные карты появятся здесь.
        Чтобы посмотреть, как это выглядит, нажмите «Загрузить пример».</div>`;
    } else if (!failed.length && !signalCount) {
      banner = '<div class="banner ok">✓ Все контрольные процедуры удовлетворительны, признаков нарушения стабильности нет.</div>';
    } else {
      banner = '<div class="banner bad">✗ Есть неудовлетворительные результаты или сигналы на контрольных картах. Требуется анализ причин и корректирующие действия.</div>';
    }

    const stats = valid.length ? `<div class="stats">
      <div class="stat"><b>${valid.length}</b><span>контрольных процедур</span></div>
      <div class="stat ${failed.length ? "bad" : ""}"><b>${failed.length}</b><span>не удовлетворяют нормативу</span></div>
      <div class="stat ${signalCount ? "bad" : ""}"><b>${signalCount}</b><span>сигналов на картах</span></div>
      ${errors ? `<div class="stat"><b>${errors}</b><span>строк с ошибками ввода</span></div>` : ""}
    </div>` : "";

    const p = state.params;
    const head = valid.length ? `<p class="meta">${esc(p.name || "Показатель не указан")}${p.units ? ", " + esc(p.units) : ""} ·
      σr = ${esc(p.sigma_r || "—")} %, σRл = ${esc(p.sigma_R || "—")} %, Δл = ${VLK.deltaLab(p) > 0 ? pct(VLK.deltaLab(p)) : "—"} % ·
      отчёт от ${new Date().toLocaleDateString("ru-RU")}</p>` : "";

    $("#summary").innerHTML = head + banner + stats;
    $("#charts").innerHTML = blocks;
  }

  function signalList(items, sig) {
    const keys = Object.keys(sig);
    if (!keys.length) return '<p class="stable">✓ Признаков нарушения стабильности не выявлено.</p>';
    return '<ul class="signals">' + keys.map((k) => {
      const r = items[k - 1];
      return `<li>Точка ${k} (строка ${r.row}${r.date ? ", " + esc(r.date) : ""}): ${sig[k].join("; ")}</li>`;
    }).join("") + "</ul>";
  }

  function legend(lim, hasBad) {
    return `<div class="legend">
      <span><i style="border-color:#555"></i>Средняя линия</span>
      <span><i style="border-color:#d08a1a;border-top-style:dashed"></i>Предел предупреждения</span>
      <span><i style="border-color:#b03030"></i>Предел действия</span>
      ${hasBad ? '<span><i class="dot" style="background:#b03030"></i>Норматив не выполнен</span>' : ""}
      <span>◯ сигнал нарушения стабильности</span></div>`;
  }

  function niceStep(range) {
    const raw = range / 5, p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
    return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  }

  function chartSVG(items, lim, sig) {
    const W = 760, H = 270, m = { l: 46, r: 14, t: 12, b: 36 };
    const ys = items.map((r) => r.rel);
    const top = Math.max(lim.action, ...ys.map(Math.abs)) * 1.12;
    const bottom = lim.twoSided ? -top : 0;
    const n = items.length;
    const sx = (i) => m.l + (i + 0.5) * (W - m.l - m.r) / n;
    const sy = (v) => m.t + (top - v) / (top - bottom) * (H - m.t - m.b);
    const out = [];

    const step = niceStep(top - bottom);
    for (let v = Math.ceil(bottom / step) * step; v <= top + 1e-9; v += step) {
      out.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="#ececec"/>`,
        `<text x="${m.l - 6}" y="${sy(v) + 4}" text-anchor="end">${fmt(Math.round(v * 100) / 100)}</text>`);
    }
    const hline = (v, color, dash, w = 1.2) =>
      out.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="${color}" stroke-width="${w}" ${dash ? 'stroke-dasharray="6 4"' : ""}/>`);
    hline(lim.cl, "#555", false, 1);
    for (const s of lim.twoSided ? [1, -1] : [1]) {
      hline(s * lim.warn, "#d08a1a", true);
      hline(s * lim.action, "#b03030", false, 1.4);
    }

    out.push(`<polyline fill="none" stroke="#2f5d8a" stroke-width="1.6" points="${ys.map((y, i) => `${sx(i)},${sy(y)}`).join(" ")}"/>`);
    items.forEach((r, i) => {
      const tip = `Точка ${i + 1}, строка ${r.row}${r.date ? " (" + esc(r.date) + ")" : ""}: ${pct(r.rel)} %${r.ok ? "" : " — норматив не выполнен"}`;
      if (sig[i + 1]) out.push(`<circle cx="${sx(i)}" cy="${sy(r.rel)}" r="9" fill="none" stroke="#b03030" stroke-width="1.8"/>`);
      out.push(`<circle cx="${sx(i)}" cy="${sy(r.rel)}" r="${r.ok ? 3.5 : 5}" fill="${r.ok ? "#2f5d8a" : "#b03030"}"><title>${tip}</title></circle>`);
    });

    const every = Math.ceil(n / 15);
    items.forEach((_, i) => {
      if (i % every === 0 || i === n - 1) out.push(`<text x="${sx(i)}" y="${H - m.b + 16}" text-anchor="middle">${i + 1}</text>`);
    });
    out.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="#999"/>`,
      `<text x="${(m.l + W - m.r) / 2}" y="${H - 4}" text-anchor="middle" fill="#66727f">Номер точки на карте</text>`,
      `<text transform="translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)" text-anchor="middle" fill="#66727f">${lim.twoSided ? "отклонение, % от C" : "% от X̄"}</text>`);

    return `<svg viewBox="0 0 ${W} ${H}" font-size="11" font-family="system-ui, Arial, sans-serif" role="img" aria-label="Контрольная карта">${out.join("")}</svg>`;
  }

  // ---------- кнопки ----------
  $("#add-row").addEventListener("click", () => {
    state.rows.push(emptyRow());
    renderTable();
    focusCell(state.rows.length - 1, "date");
  });

  $("#clear").addEventListener("click", () => {
    if (!confirm("Удалить все строки и параметры? Отменить это действие будет нельзя.")) return;
    state = defaults();
    renderParams();
    renderTable();
  });

  $("#example").addEventListener("click", () => {
    const hasData = state.rows.some((r) => Object.values(r).some((v) => String(v).trim()));
    if (hasData && !confirm("Заменить текущие данные примером?")) return;
    state = {
      params: { name: "Аммоний-ион (пример)", units: "мг/дм³", sigma_r: "4", sigma_R: "6", delta: "15", delta_lab: "", useLab: false },
      rows: VLK.rowsFromTable(VLK.parseTable(EXAMPLE_CSV)),
    };
    renderParams();
    renderTable();
  });

  function readFile(input, cb) {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { try { cb(reader.result); } catch (err) { alert("Не удалось прочитать файл: " + err.message); } input.value = ""; };
    reader.readAsText(file, "utf-8");
  }

  $("#import-csv").addEventListener("change", (e) => readFile(e.target, (text) => {
    const rows = VLK.rowsFromTable(VLK.parseTable(text));
    if (!rows.length) throw new Error("в файле нет строк с данными");
    const hasData = state.rows.some((r) => Object.values(r).some((v) => String(v).trim()));
    const append = hasData && confirm(`Найдено строк: ${rows.length}.\nОК — добавить к текущим данным, Отмена — заменить ими текущие.`);
    state.rows = append ? state.rows.filter((r) => Object.values(r).some((v) => String(v).trim())).concat(rows) : rows;
    renderTable();
  }));

  $("#export-csv").addEventListener("click", () =>
    download(fileBase() + ".csv", VLK.toCSV(state.rows.filter((r) => Object.values(r).some((v) => String(v).trim()))), "text/csv;charset=utf-8"));

  $("#save-project").addEventListener("click", () =>
    download(fileBase() + ".vlk.json", JSON.stringify({ app: "vlk-web", version: 1, ...state }, null, 1), "application/json"));

  $("#open-project").addEventListener("change", (e) => readFile(e.target, (text) => {
    const data = JSON.parse(text);
    if (!data.params || !Array.isArray(data.rows)) throw new Error("это не файл проекта ВЛК");
    state = { params: { ...defaults().params, ...data.params }, rows: data.rows.map((r) => ({ ...emptyRow(), ...r })) };
    renderParams();
    renderTable();
  }));

  $("#print").addEventListener("click", () => window.print());

  // ---------- старт ----------
  renderParams();
  renderTable();
})();
