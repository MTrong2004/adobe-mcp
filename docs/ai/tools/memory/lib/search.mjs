// BM25 trong bộ nhớ — xếp hạng văn bản chính xác, tốc độ cao không cần vector DB.

export class Bm25 {
  constructor(docTokens, { k1 = 1.2, b = 0.75 } = {}) {
    this.k1 = k1;
    this.b = b;
    this.tf = [];
    this.len = [];
    this.df = new Map();
    let total = 0;
    for (const tokens of docTokens) {
      const m = new Map();
      for (const t of tokens) m.set(t, (m.get(t) ?? 0) + 1);
      for (const t of m.keys()) this.df.set(t, (this.df.get(t) ?? 0) + 1);
      this.tf.push(m);
      this.len.push(tokens.length);
      total += tokens.length;
    }
    this.N = docTokens.length;
    this.avg = total / Math.max(1, this.N);
  }

  idf(t) {
    const df = this.df.get(t) ?? 0;
    return Math.log(1 + (this.N - df + 0.5) / (df + 0.5));
  }

  /** Trả [{i, score}] giảm dần theo điểm BM25. filter(i) -> false để bỏ qua. */
  search(queryTokens, { limit = 10, filter = null } = {}) {
    const q = [...new Set(queryTokens)].filter((t) => this.df.has(t));
    if (!q.length) return [];
    const weights = q.map((t) => [t, this.idf(t) * (t.includes('_') ? 1.6 : 1)]);
    const scores = [];
    for (let i = 0; i < this.N; i++) {
      if (filter && !filter(i)) continue;
      const tf = this.tf[i];
      let s = 0;
      for (const [t, w] of weights) {
        const f = tf.get(t);
        if (!f) continue;
        s += (w * f * (this.k1 + 1)) / (f + this.k1 * (1 - this.b + (this.b * this.len[i]) / this.avg));
      }
      if (s > 0) scores.push({ i, score: s });
    }
    return scores.sort((x, y) => y.score - x.score).slice(0, limit);
  }
}
