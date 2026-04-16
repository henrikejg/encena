#!/usr/bin/env node
/**
 * encena web — servidor Node.js local
 * Roda em http://localhost:3131
 */

const http = require('http');
const fs   = require('fs');
const path = require('path');
const { spawn, execFile } = require('child_process');

const PORT          = 3131;
const ENCENA_DIR    = path.resolve(__dirname, '..');
const ENCENA_PY     = path.join(ENCENA_DIR, 'encena.py');
const CATEGORIAS_DIR = path.join(ENCENA_DIR, 'categorias');

// ─── helpers ──────────────────────────────────────────────────────────────────

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch { return null; }
}

function writeJson(p, obj) {
  fs.writeFileSync(p, JSON.stringify(obj, null, 2) + '\n');
}

function listarCategorias() {
  return fs.readdirSync(CATEGORIAS_DIR)
    .filter(f => f.endsWith('.json') && !f.endsWith('_rascunhos.json'))
    .map(f => f.replace('.json', ''))
    .sort();
}

function getCategoria(nome) {
  const cfg       = readJson(path.join(CATEGORIAS_DIR, `${nome}.json`));
  const rascunhos = readJson(path.join(CATEGORIAS_DIR, `${nome}_rascunhos.json`)) || [];
  return { cfg, rascunhos };
}

function checkHttp(host, port, p) {
  return new Promise(resolve => {
    const req = http.get({ host, port, path: p, timeout: 2500 }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve({ ok: true, data: JSON.parse(d) }); } catch { resolve({ ok: true, data: null }); } });
    });
    req.on('error',   () => resolve({ ok: false }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false }); });
  });
}

// ─── SSE helper ───────────────────────────────────────────────────────────────

function sseRun(res, args) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection':    'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });

  const send = obj => res.write(`data: ${JSON.stringify(obj)}\n\n`);

  const proc = spawn('python3', [ENCENA_PY, ...args], {
    cwd: ENCENA_DIR,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });

  const pipe = (stream, type) =>
    stream.on('data', d =>
      d.toString().split('\n').forEach(l => { if (l.trim()) send({ t: type, s: l }); })
    );

  pipe(proc.stdout, 'o');
  pipe(proc.stderr, 'e');
  proc.on('close', code => { send({ t: 'done', code }); res.end(); });
}

// ─── body parser ─────────────────────────────────────────────────────────────

function readBody(req) {
  return new Promise((resolve, reject) => {
    let b = '';
    req.on('data', d => b += d);
    req.on('end',  () => { try { resolve(JSON.parse(b || '{}')); } catch { resolve({}); } });
    req.on('error', reject);
  });
}

// ─── router ───────────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const { pathname } = new URL(req.url, `http://localhost`);
  const method = req.method;

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const json = (obj, code = 200) => {
    res.writeHead(code, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(obj));
  };

  const err = (msg, code = 400) => json({ error: msg }, code);

  // ── static ─────────────────────────────────────────────────────────────────
  if (pathname === '/' && method === 'GET') {
    const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
    return;
  }

  // ── status ─────────────────────────────────────────────────────────────────
  if (pathname === '/api/status' && method === 'GET') {
    const [comfy, ollama] = await Promise.all([
      checkHttp('localhost', 8188, '/system_stats'),
      checkHttp('localhost', 11434, '/api/tags'),
    ]);
    let modelo = null;
    if (ollama.ok && ollama.data) {
      const ms = (ollama.data.models || []).map(m => m.name);
      modelo = ms.find(m => m === 'mistral:7b')
            || ms.find(m => m === 'mistral:latest')
            || ms.find(m => m.includes('mistral'))
            || ms[0] || null;
    }
    json({ comfy: comfy.ok, ollama: ollama.ok, modelo });
    return;
  }

  // ── nova categoria (SSE — chama encena.py para gerar tema+tags via Ollama) ─
  if (pathname === '/api/categorias' && method === 'POST') {
    const b = await readBody(req);
    if (!b.nome) { err('nome obrigatório'); return; }
    const args = ['nova-categoria', '-n', b.nome];
    if (b.cfg)         args.push('--cfg',         String(b.cfg));
    if (b.lora_nature) args.push('--lora-nature',  String(b.lora_nature));
    if (b.lora_detail) args.push('--lora-detail',  String(b.lora_detail));
    if (b.steps)       args.push('--steps',        String(b.steps));
    if (b.width)       args.push('--width',        String(b.width));
    if (b.height)      args.push('--height',       String(b.height));
    // Passa tags só se o usuário preencheu — senão o Python gera automaticamente
    const tagsRaw = typeof b.tags === 'string' ? b.tags.trim() : '';
    if (tagsRaw) args.push('--tags', tagsRaw);
    sseRun(res, args);
    return;
  }

  // ── deletar categoria ──────────────────────────────────────────────────────
  const mDelCat = pathname.match(/^\/api\/categorias\/([^/]+)$/);
  if (mDelCat && method === 'DELETE') {
    const nome = mDelCat[1];
    const cfgPath  = path.join(CATEGORIAS_DIR, `${nome}.json`);
    const rascPath = path.join(CATEGORIAS_DIR, `${nome}_rascunhos.json`);
    if (!fs.existsSync(cfgPath)) { err('Categoria não encontrada', 404); return; }
    try {
      fs.unlinkSync(cfgPath);
      if (fs.existsSync(rascPath)) fs.unlinkSync(rascPath);
      json({ ok: true });
    } catch (e) { json({ ok: false, error: e.message }); }
    return;
  }

  // ── listar categorias ──────────────────────────────────────────────────────
  if (pathname === '/api/categorias' && method === 'GET') {
    const cats = listarCategorias().map(nome => {
      const { cfg, rascunhos } = getCategoria(nome);
      return {
        nome,
        n_prompts:   cfg?.prompts?.length || 0,
        n_rascunhos: rascunhos.length,
        tags:        cfg?.tags || [],
        cfg: cfg ? {
          cfg: cfg.cfg, lora_nature: cfg.lora_nature,
          lora_detail: cfg.lora_detail, steps: cfg.steps,
          sampler: cfg.sampler, scheduler: cfg.scheduler,
          width: cfg.width, height: cfg.height,
          tags: cfg.tags || [],
          biomas:    cfg.biomas    || [],
          elementos: cfg.elementos || [],
        } : null,
      };
    });
    json(cats);
    return;
  }

  // ── categoria detalhe ──────────────────────────────────────────────────────
  const mCat = pathname.match(/^\/api\/categoria\/([^/]+)$/);
  if (mCat && method === 'GET') {
    const { cfg, rascunhos } = getCategoria(mCat[1]);
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    json({ nome: mCat[1], cfg, rascunhos });
    return;
  }

  // ── estilos ────────────────────────────────────────────────────────────────
  if (pathname === '/api/estilos' && method === 'GET') {
    json({
      padrao:         { descricao: 'DSLR versátil, tudo nítido',                                     captura: 'Canon EOS R5, 24-70mm f/2.8, f/8, ISO 100' },
      ultrawide:      { descricao: 'Grande angular extremo — céu enorme, perspectiva dramática',      captura: 'Canon EOS R5, 16-35mm f/2.8, f/11, ISO 100' },
      telefoto:       { descricao: 'Telefoto — sujeito isolado, fundo comprimido e desfocado',        captura: 'Sony A7R V, 400mm f/2.8, f/4, ISO 400' },
      medioformato:   { descricao: "Médio formato — detalhe extraordinário, 'pop 3D', dinâmica extrema", captura: 'Hasselblad X2D, 45mm f/3.5, f/8, ISO 64' },
      noturno:        { descricao: 'Noturno — abertura máxima, grain atmosférico de ISO alto',         captura: 'Sony A7R V, 24mm f/1.4, f/2, ISO 3200' },
      longaexposicao: { descricao: 'Longa exposição — água e nuvens sedosas, 30s com tripé e ND',      captura: 'Canon EOS R5, 24mm f/11, 30s exposure, ISO 100, ND filter' },
      analogico:      { descricao: 'Scan de filme analógico — paleta orgânica, grão de película',     captura: 'Hasselblad medium format, Kodak Portra 400 film scan' },
      aereo:          { descricao: 'Drone — perspectiva aérea, tudo nítido ao horizonte',              captura: 'DJI Mavic 3 Pro, 24mm equivalent, f/8, ISO 100' },
    });
    return;
  }

  // ── gerar prompts (SSE) ────────────────────────────────────────────────────
  if (pathname === '/api/prompts/gerar' && method === 'POST') {
    const b = await readBody(req);
    if (!b.categoria) { err('categoria obrigatória'); return; }
    const args = ['prompts', '-c', b.categoria, '-q', String(b.quantidade || 3)];
    if (b.modo)        args.push('-m', b.modo);
    if (b.livre)       args.push('--livre');
    if (b.estilo)      args.push('-e', b.estilo);
    if (b.bioma)       args.push('--bioma', b.bioma);
    if (b.hora)        args.push('--hora', b.hora);
    if (b.clima)       args.push('--clima', b.clima);
    if (b.perspectiva) args.push('--perspectiva', b.perspectiva);
    if (b.elemento)    args.push('--elemento', b.elemento);
    if (b.simular)     args.push('--simular');
    sseRun(res, args);
    return;
  }

  // ── gerar imagens (SSE) ────────────────────────────────────────────────────
  if (pathname === '/api/imagens/gerar' && method === 'POST') {
    const b = await readBody(req);
    const args = ['imagens'];
    if (b.todas) {
      args.push('--todas');
    } else {
      if (!b.categorias) { err('categorias obrigatório'); return; }
      args.push('-c', b.categorias);
    }
    args.push('-q', String(b.quantidade || 1));
    if (b.prompt_nome)  args.push('--prompt-nome', b.prompt_nome);
    if (b.orientacao)   args.push('--orientacao', b.orientacao);
    sseRun(res, args);
    return;
  }

  // ── experimentar (SSE) ────────────────────────────────────────────────────
  if (pathname === '/api/experimentar' && method === 'POST') {
    const b = await readBody(req);
    if (!b.categoria) { err('categoria obrigatória'); return; }
    const args = ['experimentar', '-c', b.categoria, '-q', String(b.quantidade || 1)];
    if (b.modo)        args.push('-m', b.modo);
    if (b.livre)       args.push('--livre');
    if (b.estilo)      args.push('-e', b.estilo);
    if (b.bioma)       args.push('--bioma', b.bioma);
    if (b.hora)        args.push('--hora', b.hora);
    if (b.clima)       args.push('--clima', b.clima);
    if (b.perspectiva) args.push('--perspectiva', b.perspectiva);
    if (b.elemento)    args.push('--elemento', b.elemento);
    if (b.orientacao)  args.push('--orientacao', b.orientacao);
    sseRun(res, args);
    return;
  }

  // ── promover rascunho ─────────────────────────────────────────────────────
  if (pathname === '/api/promover' && method === 'POST') {
    const b = await readBody(req);
    if (!b.categoria || !b.nome) { err('categoria e nome obrigatórios'); return; }
    execFile('python3', [ENCENA_PY, 'promover', b.nome, '-c', b.categoria],
      { cwd: ENCENA_DIR },
      (e, stdout, stderr) => json({ ok: !e, stdout, stderr })
    );
    return;
  }

  // ── bulk delete prompts ───────────────────────────────────────────────────
  const mBulkP = pathname.match(/^\/api\/prompts\/([^/]+)\/bulk-delete$/);
  if (mBulkP && method === 'POST') {
    const [, categoria] = mBulkP;
    const b = await readBody(req);
    if (!b.names || !Array.isArray(b.names)) { err('names obrigatório'); return; }
    const cfgPath = path.join(CATEGORIAS_DIR, `${categoria}.json`);
    const cfg = readJson(cfgPath);
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const nomes = new Set(b.names);
    cfg.prompts = (cfg.prompts || []).filter(p => !nomes.has(p.name));
    writeJson(cfgPath, cfg);
    json({ ok: true, removed: b.names.length });
    return;
  }

  // ── bulk delete rascunhos ─────────────────────────────────────────────────
  const mBulkR = pathname.match(/^\/api\/rascunhos\/([^/]+)\/bulk-delete$/);
  if (mBulkR && method === 'POST') {
    const [, categoria] = mBulkR;
    const b = await readBody(req);
    if (!b.names || !Array.isArray(b.names)) { err('names obrigatório'); return; }
    const rascPath = path.join(CATEGORIAS_DIR, `${categoria}_rascunhos.json`);
    const list = readJson(rascPath) || [];
    const nomes = new Set(b.names);
    const filtered = list.filter(r => !nomes.has(r.name));
    if (filtered.length === 0) { try { fs.unlinkSync(rascPath); } catch {} }
    else writeJson(rascPath, filtered);
    json({ ok: true, removed: b.names.length });
    return;
  }

  // ── editar prompt ─────────────────────────────────────────────────────────
  const mEditP = pathname.match(/^\/api\/prompts\/([^/]+)\/([^/]+)$/);
  if (mEditP && method === 'PUT') {
    const [, categoria, nomeAntigo] = mEditP;
    const b = await readBody(req);
    const cfgPath = path.join(CATEGORIAS_DIR, `${categoria}.json`);
    const cfg = readJson(cfgPath);
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const idx = cfg.prompts.findIndex(p => p.name === nomeAntigo);
    if (idx === -1) { err('Prompt não encontrado', 404); return; }
    cfg.prompts[idx] = { name: b.name || nomeAntigo, text: b.text };
    writeJson(cfgPath, cfg);
    json({ ok: true });
    return;
  }

  // ── remover prompt ────────────────────────────────────────────────────────
  const mDel = pathname.match(/^\/api\/prompts\/([^/]+)\/([^/]+)$/);
  if (mDel && method === 'DELETE') {
    const [, categoria, nome] = mDel;
    execFile('python3', [ENCENA_PY, 'remover', nome, '-c', categoria],
      { cwd: ENCENA_DIR },
      (e, stdout, stderr) => json({ ok: !e, stdout, stderr })
    );
    return;
  }

  // ── editar rascunho ───────────────────────────────────────────────────────
  const mEditR = pathname.match(/^\/api\/rascunhos\/([^/]+)\/([^/]+)$/);
  if (mEditR && method === 'PUT') {
    const [, categoria, nomeAntigo] = mEditR;
    const b = await readBody(req);
    const rascPath = path.join(CATEGORIAS_DIR, `${categoria}_rascunhos.json`);
    const rascunhos = readJson(rascPath) || [];
    const idx = rascunhos.findIndex(r => r.name === nomeAntigo);
    if (idx === -1) { err('Rascunho não encontrado', 404); return; }
    rascunhos[idx] = { name: b.name || nomeAntigo, text: b.text };
    writeJson(rascPath, rascunhos);
    json({ ok: true });
    return;
  }

  // ── editar config da categoria ────────────────────────────────────────────
  const mEditCfg = pathname.match(/^\/api\/categoria\/([^/]+)\/cfg$/);
  if (mEditCfg && method === 'PUT') {
    const nome = mEditCfg[1];
    const b = await readBody(req);
    const cfgPath = path.join(CATEGORIAS_DIR, `${nome}.json`);
    const cfg = readJson(cfgPath);
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const nums = ['cfg','steps','width','height','lora_nature','lora_detail'];
    const strs = ['sampler','scheduler','output_subdir','negative'];
    nums.forEach(k => { if (b[k] !== undefined && b[k] !== '') cfg[k] = parseFloat(b[k]); });
    strs.forEach(k => { if (b[k] !== undefined) cfg[k] = b[k]; });
    if (b.tags !== undefined) {
      cfg.tags = Array.isArray(b.tags) ? b.tags
        : b.tags.split(',').map(t => t.trim()).filter(Boolean);
    }
    writeJson(cfgPath, cfg);
    json({ ok: true });
    return;
  }

  // ── gerar tema via Ollama (SSE) ───────────────────────────────────────────
  const mTema = pathname.match(/^\/api\/categoria\/([^/]+)\/tema$/);
  if (mTema && method === 'POST') {
    sseRun(res, ['gerar-tema', '-c', mTema[1]]);
    return;
  }

  // ── descartar rascunho ────────────────────────────────────────────────────
  const mRasc = pathname.match(/^\/api\/rascunhos\/([^/]+)\/([^/]+)$/);
  if (mRasc && method === 'DELETE') {
    const [, categoria, nome] = mRasc;
    const p = path.join(CATEGORIAS_DIR, `${categoria}_rascunhos.json`);
    try {
      const list = (readJson(p) || []).filter(r => r.name !== nome);
      if (list.length === 0) { try { fs.unlinkSync(p); } catch {} }
      else writeJson(p, list);
      json({ ok: true });
    } catch (e) { json({ ok: false, error: e.message }); }
    return;
  }

  res.writeHead(404); res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`\n  encena web  →  http://localhost:${PORT}\n`);
});
