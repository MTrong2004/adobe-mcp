// Dựng đồ thị phụ thuộc mã nguồn: import, component tag usage, assets, links.

import path from 'node:path';
import { toPosix } from './util.mjs';

const IMPORT_EXTS = ['', '.tsx', '.ts', '.jsx', '.js', '.mjs', '.cjs', '.vue', '.svelte', '.astro', '.css', '.scss',
  '/index.tsx', '/index.ts', '/index.jsx', '/index.js', '/index.mjs', '/index.vue', '/index.svelte'];
const DEFAULT_ALIASES = { '@/': ['', 'src/'] };

export function resolveImport(fromRel, importPath, allFiles, aliases = DEFAULT_ALIASES) {
  const targets = [];
  if (importPath.startsWith('./') || importPath.startsWith('../')) {
    const dir = path.posix.dirname(fromRel);
    targets.push(path.posix.normalize(path.posix.join(dir, importPath)));
  } else {
    // Alias (tsconfig paths); không khớp alias nào = thư viện ngoài
    for (const [prefix, bases] of Object.entries(aliases)) {
      if (!importPath.startsWith(prefix)) continue;
      for (const base of bases) targets.push(base + importPath.slice(prefix.length));
    }
  }
  for (let target of targets) {
    // import "./a.js" trong TS/ESM thực chất trỏ tới a.ts
    const bare = target.replace(/\.(js|mjs|cjs|jsx)$/, '');
    for (const t of bare === target ? [target] : [target, bare]) {
      for (const ext of IMPORT_EXTS) {
        if (allFiles[t + ext]) return t + ext;
      }
    }
  }
  return null;
}

export function buildGraph(index, cfg = {}) {
  const t0 = Date.now();
  const F = index.files;
  const rels = Object.keys(F).filter((r) => F[r].f);

  const g = {
    files: {},
    out: new Map(), // rel -> [ { to, type, label } ]
    in: new Map(),  // rel -> [ { from, type, label } ]
    tagsToComponent: new Map(), // TagName -> rel (e.g. 'Landing' -> 'components/v6/Landing.tsx')
    stats: {},
  };

  const edgeKeys = new Set();
  const addEdge = (from, to, type, label = '') => {
    if (!from || !to || from === to) return;
    const key = `${from}|${to}|${type}|${label}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);

    const e = { from, to, type, label };
    if (!g.out.has(from)) g.out.set(from, []);
    if (!g.in.has(to)) g.in.set(to, []);
    g.out.get(from).push(e);
    g.in.get(to).push(e);
  };

  // 1. Khởi tạo danh sách file & ánh xạ TagName
  for (const rel of rels) {
    const f = F[rel].f;
    g.files[rel] = {
      l: f.l,
      k: f.k,
      mod: f.mod,
      sym: f.sym || [],
      ui: f.ui || [],
      tokens: f.tokens || [],
      assets: f.assets || [],
    };

    // Ánh xạ Component Name từ tên file hoặc exported symbols
    const baseName = rel.split('/').pop().replace(/\.(tsx|ts|jsx|js)$/, '');
    if (/^[A-Z]/.test(baseName)) {
      g.tagsToComponent.set(baseName, rel);
    }
    for (const s of f.sym) {
      if (/^[A-Z]/.test(s)) {
        g.tagsToComponent.set(s, rel);
      }
    }
  }

  // 2. Nối các cạnh: Import & Component Usage & Assets
  for (const rel of rels) {
    const f = F[rel].f;

    // Nối Import
    for (const imp of f.imports || []) {
      const resolved = resolveImport(rel, imp, g.files, cfg.aliases);
      if (resolved) {
        addEdge(rel, resolved, 'import');
      }
    }

    // Nối Component Usage (JSX tag <Landing />)
    for (const tag of f.tags || []) {
      const targetRel = g.tagsToComponent.get(tag);
      if (targetRel && targetRel !== rel) {
        addEdge(rel, targetRel, 'uses', `<${tag} />`);
      }
    }

    // Nối quan hệ Asset đồ hoạ
    for (const assetPath of f.assets || []) {
      if (!g.files[assetPath]) {
        g.files[assetPath] = {
          l: 'asset',
          k: 'asset',
          mod: assetPath.split('/')[1] || 'asset',
          sym: [assetPath.split('/').pop()],
          ui: [],
          tokens: [assetPath.split('/').pop()],
          assets: [],
        };
      }
      if (f.l === 'script') {
        addEdge(rel, assetPath, 'asset-producer', 'tạo/sửa asset');
      } else {
        addEdge(rel, assetPath, 'asset-consumer', 'dùng asset');
      }
    }
  }

  // 3. Nối lời gọi API nội bộ: fetch('/api/x') -> app/api/x/route.ts (App Router) hoặc pages/api/x.ts (Pages Router)
  const routes = [];
  for (const rel of rels) {
    let m = /(?:^|\/)app\/(.+)\/route\.(?:ts|js|mjs)$/.exec(rel);
    let url = m ? m[1] : null;
    if (!m) {
      m = /(?:^|\/)pages\/(api\/.+?)(?:\/index)?\.(?:ts|js|tsx|jsx)$/.exec(rel);
      url = m ? m[1] : null;
    }
    if (!url) continue;
    // Bỏ route group "(nhom)"; đoạn động [id] / [...slug] khớp mọi giá trị
    const segs = url.split('/').filter((s) => !/^\(.*\)$/.test(s));
    const pattern = segs
      .map((s) => (/^\[\[?\.\.\./.test(s) ? '.*' : /^\[.*\]$/.test(s) ? '[^/]+' : s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
      .join('/');
    routes.push({ rel, url: '/' + segs.join('/'), re: new RegExp(`^/${pattern}/?$`) });
  }
  g.routes = routes.map(({ rel, url }) => ({ rel, url }));
  let apiCalls = 0;
  let apiLinked = 0;
  for (const rel of rels) {
    for (const ep of F[rel].f.endpoints || []) {
      if (!ep.startsWith('/')) continue; // URL ngoài hoặc ghép từ biến: không nối
      apiCalls++;
      // `${id}` trong template literal coi như một đoạn động
      const probe = ep.replace(/\$\{[^}]*\}/g, 'x');
      const hit = routes.find((r) => r.re.test(probe));
      if (hit) {
        apiLinked++;
        addEdge(rel, hit.rel, 'api', ep);
      }
    }
  }
  g.stats.apiCalls = apiCalls;
  g.stats.apiLinked = apiLinked;

  g.stats.ms = Date.now() - t0;
  g.stats.edges = edgeKeys.size;
  return g;
}
