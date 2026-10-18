/* Client-side football maths (mirrors entropy_xi/models/markets.py) — used by the line calculator. */
(function (global) {
  const MAXG = 11;
  const LOGF = [];
  for (let k = 0; k < MAXG; k++) LOGF.push(k === 0 ? 0 : LOGF[k - 1] + Math.log(k));
  const pmf = (lam) => Array.from({ length: MAXG }, (_, k) => Math.exp(k * Math.log(Math.max(lam, 1e-9)) - lam - LOGF[k]));

  function matrix(lh, la, rho) {
    rho = rho == null ? -0.06 : rho;
    const ph = pmf(lh), pa = pmf(la);
    const m = ph.map((x) => pa.map((y) => x * y));
    m[0][0] *= Math.max(1 - lh * la * rho, 1e-6);
    m[0][1] *= Math.max(1 + lh * rho, 1e-6);
    m[1][0] *= Math.max(1 + la * rho, 1e-6);
    m[1][1] *= Math.max(1 - rho, 1e-6);
    let s = 0;
    m.forEach((r) => r.forEach((v) => (s += v)));
    return m.map((r) => r.map((v) => v / s));
  }

  function splitLine(line) {
    const q = Math.round(line * 4);
    if (q % 2 !== 0) return [(q - 1) / 4, (q + 1) / 4];
    return [line, line];
  }
  const comp = (x) => (x > 1e-9 ? 1 : x < -1e-9 ? -1 : 0);
  function settle(diff, line) {
    const [a, b] = splitLine(line);
    return (comp(diff + a) + comp(diff + b)) / 2;
  }
  const KEY = { "1": "win", "0.5": "half_win", "0": "push", "-0.5": "half_loss", "-1": "loss" };

  function handicap(m, line, side) {
    const r = { win: 0, half_win: 0, push: 0, half_loss: 0, loss: 0 };
    const sl = side === "home" ? line : -line;
    for (let i = 0; i < MAXG; i++) for (let j = 0; j < MAXG; j++) {
      const d = side === "home" ? i - j : j - i;
      r[KEY[String(settle(d, sl))]] += m[i][j];
    }
    return r;
  }
  function totals(m, line, side) {
    const r = { win: 0, half_win: 0, push: 0, half_loss: 0, loss: 0 };
    const [a, b] = splitLine(line);
    for (let i = 0; i < MAXG; i++) for (let j = 0; j < MAXG; j++) {
      const g = i + j;
      const v = side === "over" ? (comp(g - a) + comp(g - b)) / 2 : (comp(a - g) + comp(b - g)) / 2;
      r[KEY[String(v)]] += m[i][j];
    }
    return r;
  }
  function ev(pr, odds) {
    const w = odds - 1;
    return pr.win * w + (pr.half_win * w) / 2 - pr.half_loss / 2 - pr.loss;
  }
  function effP(pr) {
    const won = pr.win + 0.5 * pr.half_win;
    const dec = won + pr.loss + 0.5 * pr.half_loss;
    return dec > 1e-9 ? won / dec : 0.5;
  }
  function fair(pr) {
    const den = pr.win + pr.half_win / 2;
    return den > 1e-9 ? 1 + (pr.half_loss / 2 + pr.loss) / den : Infinity;
  }
  function outcome1x2(m) {
    let h = 0, d = 0, a = 0;
    for (let i = 0; i < MAXG; i++) for (let j = 0; j < MAXG; j++) {
      if (i > j) h += m[i][j]; else if (i === j) d += m[i][j]; else a += m[i][j];
    }
    return [h, d, a];
  }

  /* Asian handicap wording: -0.75 → 半/一 (主让); +0.25 → 受平/半 */
  const AH_ZH = { 0: "平手", 0.25: "平/半", 0.5: "半球", 0.75: "半/一", 1: "一球", 1.25: "一/球半", 1.5: "球半", 1.75: "球半/两",
    2: "两球", 2.25: "两/两球半", 2.5: "两球半", 2.75: "两球半/三", 3: "三球", 3.25: "三/三球半", 3.5: "三球半", 3.75: "三球半/四", 4: "四球" };
  function fmtSigned(x) {
    const s = Number(x).toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
    return x > 0 ? "+" + s : x === 0 ? "0" : s;
  }
  function ahWord(line) {
    const a = Math.abs(line);
    return AH_ZH[a] || a.toString();
  }
  function ouWord(line) {
    const q = Math.round(line * 4);
    if (q % 2 !== 0) { const [a, b] = splitLine(line); return `${trim(a)}/${trim(b)}`; }
    return trim(line);
  }
  const trim = (x) => Number(x).toFixed(2).replace(/0+$/, "").replace(/\.$/, "");

  global.FB = { matrix, handicap, totals, ev, effP, fair, outcome1x2, splitLine, fmtSigned, ahWord, ouWord, trim };
})(window);
