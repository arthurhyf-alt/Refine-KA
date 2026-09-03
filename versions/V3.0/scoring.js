export const DIMENSIONS = [
  { key: "export", label: "出口 / 外需", defaultWeight: 20 },
  { key: "industrial", label: "工业增加值", defaultWeight: 20 },
  { key: "jobs", label: "招聘网站岗位数量（人力资源）", defaultWeight: 15 },
  { key: "technology", label: "技术突破", defaultWeight: 15 },
  { key: "policy", label: "政策导向", defaultWeight: 15 },
  { key: "finance", label: "政府补贴 / 政府投资", defaultWeight: 15 },
];

export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function defaultWeights() {
  return Object.fromEntries(DIMENSIONS.map((dimension) => [dimension.key, dimension.defaultWeight]));
}

export function normalizeWeights(input) {
  const values = Object.fromEntries(DIMENSIONS.map((dimension) => [
    dimension.key,
    Math.max(0, Math.round(Number(input?.[dimension.key] ?? dimension.defaultWeight))),
  ]));
  const total = Object.values(values).reduce((sum, value) => sum + value, 0);
  if (!total) return defaultWeights();
  const exact = DIMENSIONS.map((dimension) => ({
    key: dimension.key,
    value: values[dimension.key] * 100 / total,
  }));
  const normalized = Object.fromEntries(exact.map((item) => [item.key, Math.floor(item.value)]));
  let remainder = 100 - Object.values(normalized).reduce((sum, value) => sum + value, 0);
  exact.sort((a, b) => (b.value - Math.floor(b.value)) - (a.value - Math.floor(a.value)));
  for (let index = 0; index < remainder; index += 1) normalized[exact[index].key] += 1;
  return normalized;
}

export function rebalanceWeights(input, changedKey, requestedValue) {
  const current = normalizeWeights(input);
  const changedValue = clamp(Math.round(Number(requestedValue)), 0, 100);
  const otherKeys = DIMENSIONS.map((dimension) => dimension.key).filter((key) => key !== changedKey);
  const remaining = 100 - changedValue;
  if (!otherKeys.length) return { [changedKey]: 100 };
  if (!remaining) return Object.fromEntries(DIMENSIONS.map((dimension) => [dimension.key, dimension.key === changedKey ? 100 : 0]));

  const otherTotal = otherKeys.reduce((sum, key) => sum + current[key], 0);
  const exact = otherKeys.map((key) => ({
    key,
    value: otherTotal ? current[key] * remaining / otherTotal : remaining / otherKeys.length,
  }));
  const next = { [changedKey]: changedValue };
  for (const item of exact) next[item.key] = Math.floor(item.value);
  let remainder = remaining - otherKeys.reduce((sum, key) => sum + next[key], 0);
  exact.sort((a, b) => (b.value - Math.floor(b.value)) - (a.value - Math.floor(a.value)));
  for (let index = 0; index < remainder; index += 1) next[exact[index].key] += 1;
  return next;
}

export function effectiveScore(score, confidence = 1) {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return 50;
  const s = clamp(Number(score), 0, 100);
  const c = clamp(Number(confidence ?? 1), 0, 1);
  return 50 + (s - 50) * c;
}

export function scoreIndustry(record, weights) {
  let weighted = 0;
  let configuredWeight = 0;
  let observedWeight = 0;
  const breakdown = {};

  for (const dimension of DIMENSIONS) {
    const weight = Number(weights[dimension.key] ?? dimension.defaultWeight);
    const raw = record.metrics?.[dimension.key]?.score;
    const confidence = record.metrics?.[dimension.key]?.confidence ?? 0;
    const observed = raw !== null && raw !== undefined && !Number.isNaN(Number(raw));
    const effective = observed ? effectiveScore(raw, confidence) : null;
    breakdown[dimension.key] = { raw, confidence, effective, observed, weight, contribution: 0 };
    configuredWeight += weight;
    if (observed) {
      weighted += effective * weight;
      observedWeight += weight;
    }
  }

  const score = observedWeight ? weighted / observedWeight : 50;
  for (const dimension of DIMENSIONS) {
    const item = breakdown[dimension.key];
    item.contribution = item.observed && observedWeight ? item.effective * item.weight / observedWeight : 0;
  }
  const coverage = configuredWeight ? observedWeight / configuredWeight : 0;
  const tier = !observedWeight ? "数据不足" : score >= 65 ? "优先关注" : score >= 55 ? "持续观察" : score >= 45 ? "中性" : "谨慎";
  return { ...record, totalScore: score, coverage, tier, breakdown };
}

export function rankIndustries(records, weights) {
  return records.map((record) => scoreIndustry(record, weights)).sort((a, b) => b.totalScore - a.totalScore);
}

export function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) return [];
  const split = (line) => {
    const result = [];
    let token = "";
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === '"' && line[i + 1] === '"') { token += '"'; i += 1; }
      else if (ch === '"') quoted = !quoted;
      else if (ch === "," && !quoted) { result.push(token.trim()); token = ""; }
      else token += ch;
    }
    result.push(token.trim());
    return result;
  };
  const headers = split(lines[0]);
  return lines.slice(1).map((line, index) => {
    const cells = split(line);
    const row = Object.fromEntries(headers.map((h, i) => [h, cells[i] ?? ""]));
    const metrics = {};
    for (const d of DIMENSIONS) {
      const scoreText = row[`${d.key}_score`];
      const confidenceText = row[`${d.key}_confidence`];
      metrics[d.key] = {
        score: scoreText === "" || scoreText === undefined ? null : Number(scoreText),
        confidence: confidenceText === "" || confidenceText === undefined ? 0.7 : Number(confidenceText),
        evidence: row[`${d.key}_evidence`] || "CSV导入",
      };
    }
    return {
      id: row.id || `csv-${index + 1}`,
      industry: row.industry || `未命名行业${index + 1}`,
      region: row.region || "全国",
      updatedAt: row.updated_at || new Date().toISOString().slice(0, 10),
      metrics,
    };
  });
}

export function toCsv(records) {
  const headers = ["id", "industry", "region", "updated_at"];
  for (const d of DIMENSIONS) headers.push(`${d.key}_score`, `${d.key}_confidence`, `${d.key}_evidence`);
  const esc = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const rows = records.map((r) => {
    const values = [r.id, r.industry, r.region, r.updatedAt];
    for (const d of DIMENSIONS) {
      const m = r.metrics?.[d.key] || {};
      values.push(m.score ?? "", m.confidence ?? "", m.evidence ?? "");
    }
    return values.map(esc).join(",");
  });
  return [headers.join(","), ...rows].join("\n");
}
