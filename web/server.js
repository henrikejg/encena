#!/usr/bin/env node
/**
 * encena web — servidor Node.js local
 * Roda em http://localhost:3131
 */

const http = require('http');
const fs   = require('fs');
const path = require('path');
const os   = require('os');
const { spawn, execFile } = require('child_process');

const PORT          = 3131;
const ENCENA_DIR    = path.resolve(__dirname, '..');
const ENCENA_PY     = path.join(ENCENA_DIR, 'encena.py');
const CATEGORIAS_DIR = path.join(ENCENA_DIR, 'categorias');
const COMFY_OUTPUT  = process.env.COMFY_OUTPUT || path.join(os.homedir(), 'ComfyUI', 'output');

// ─── helpers ──────────────────────────────────────────────────────────────────

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch { return null; }
}

function writeJson(p, obj) {
  fs.writeFileSync(p, JSON.stringify(obj, null, 2) + '\n');
}

function readPngMeta(filepath) {
  const buf = fs.readFileSync(filepath);
  // IHDR é sempre o primeiro chunk (offset 8): width @ 16, height @ 20
  const meta = {
    _width:  buf.length >= 24 ? buf.readUInt32BE(16) : null,
    _height: buf.length >= 24 ? buf.readUInt32BE(20) : null,
  };
  let offset = 8;
  while (offset < buf.length - 12) {
    const len  = buf.readUInt32BE(offset);
    const type = buf.subarray(offset + 4, offset + 8).toString('ascii');
    if (type === 'tEXt') {
      const raw = buf.subarray(offset + 8, offset + 8 + len).toString('latin1');
      const nul = raw.indexOf('\0');
      if (nul !== -1) meta[raw.slice(0, nul)] = raw.slice(nul + 1);
    }
    if (type === 'IEND') break;
    offset += 12 + len;
  }
  return meta;
}

function parseComfyMeta(pngPath) {
  try {
    const raw = readPngMeta(pngPath);
    // Dimensões reais do arquivo (pós-upscale), lidas do IHDR
    const actual_width  = raw._width;
    const actual_height = raw._height;
    if (!raw.prompt) return { actual_width, actual_height };
    const p = JSON.parse(raw.prompt);
    return {
      actual_width,
      actual_height,
      checkpoint:    p['1']?.inputs?.ckpt_name        || null,
      lora_detail:   p['2']?.inputs?.lora_name        || null,
      lora_detail_s: p['2']?.inputs?.strength_model   ?? null,
      lora_nature:   p['3']?.inputs?.lora_name        || null,
      lora_nature_s: p['3']?.inputs?.strength_model   ?? null,
      positive:      p['4']?.inputs?.text             || null,
      negative:      p['5']?.inputs?.text             || null,
      latent_width:  p['6']?.inputs?.width            || null,
      latent_height: p['6']?.inputs?.height           || null,
      seed:          p['7']?.inputs?.seed             ?? null,
      steps:         p['7']?.inputs?.steps            ?? null,
      cfg:           p['7']?.inputs?.cfg              ?? null,
      sampler:       p['7']?.inputs?.sampler_name     || null,
      scheduler:     p['7']?.inputs?.scheduler        || null,
    };
  } catch { return null; }
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

// Executa múltiplos processos em sequência, transmitindo tudo num único SSE.
// Envia 'done' só após o último processo (ou imediatamente se algum falhar).
function sseRunSeq(res, argsList) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection':    'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });

  const send = obj => res.write(`data: ${JSON.stringify(obj)}\n\n`);

  function runNext(i) {
    if (i >= argsList.length) { send({ t: 'done', code: 0 }); res.end(); return; }
    const proc = spawn('python3', [ENCENA_PY, ...argsList[i]], {
      cwd: ENCENA_DIR,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    const pipe = (stream, type) =>
      stream.on('data', d =>
        d.toString().split('\n').forEach(l => { if (l.trim()) send({ t: type, s: l }); })
      );
    pipe(proc.stdout, 'o');
    pipe(proc.stderr, 'e');
    proc.on('close', code => {
      if (code !== 0) { send({ t: 'done', code }); res.end(); return; }
      runNext(i + 1);
    });
  }
  runNext(0);
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
  if (method === 'GET' && !pathname.startsWith('/api/')) {
    const mimeTypes = { '.html':'text/html;charset=utf-8', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon' };
    const filePath  = pathname === '/' ? path.join(__dirname, 'index.html')
                                       : path.join(__dirname, pathname.slice(1));
    const resolved  = path.resolve(filePath);
    // Segurança: só serve arquivos dentro do diretório web/
    if (!resolved.startsWith(path.resolve(__dirname) + path.sep) && resolved !== path.resolve(__dirname)) {
      res.writeHead(403); res.end('Forbidden'); return;
    }
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      const ext  = path.extname(resolved);
      const mime = mimeTypes[ext] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'max-age=3600' });
      fs.createReadStream(resolved).pipe(res);
      return;
    }
  }

  // ── modelos disponíveis no ComfyUI ────────────────────────────────────────
  if (pathname === '/api/comfy/models' && method === 'GET') {
    const [ckpt, lora] = await Promise.all([
      checkHttp('localhost', 8188, '/object_info/CheckpointLoaderSimple'),
      checkHttp('localhost', 8188, '/object_info/LoraLoader'),
    ]);
    const checkpoints = ckpt.ok ? (ckpt.data?.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0] ?? []) : [];
    const loras       = lora.ok ? (lora.data?.LoraLoader?.input?.required?.lora_name?.[0]             ?? []) : [];
    json({ checkpoints, loras });
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
    const b    = await readBody(req);
    const qtdV = parseInt(b.qtd_vertical)   || 0;
    const qtdH = parseInt(b.qtd_horizontal) || 0;
    if (qtdV + qtdH === 0) { err('quantidade inválida'); return; }
    if (!b.todas && !b.categorias) { err('categorias obrigatório'); return; }

    const makeArgs = (qtd, orientacao) => {
      const a = ['imagens'];
      b.todas ? a.push('--todas') : a.push('-c', b.categorias);
      a.push('-q', String(qtd), '--orientacao', orientacao);
      if (b.prompt_nome) a.push('--prompt-nome', b.prompt_nome);
      return a;
    };

    const argsList = [];
    if (qtdV > 0) argsList.push(makeArgs(qtdV, 'vertical'));
    if (qtdH > 0) argsList.push(makeArgs(qtdH, 'horizontal'));
    sseRunSeq(res, argsList);
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

  // ── votar em prompt ───────────────────────────────────────────────────────
  const mVote = pathname.match(/^\/api\/prompts\/([^/]+)\/([^/]+)\/vote$/);
  if (mVote && method === 'POST') {
    const [, categoria, nome] = mVote;
    const b = await readBody(req);
    if (!['up','down'].includes(b.vote)) { err('vote deve ser "up" ou "down"'); return; }
    const cfgPath = path.join(CATEGORIAS_DIR, `${categoria}.json`);
    const cfg = readJson(cfgPath);
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const prompt = (cfg.prompts || []).find(p => p.name === nome);
    if (!prompt) { err('Prompt não encontrado', 404); return; }
    if (!prompt.votes) prompt.votes = { up: 0, down: 0 };
    prompt.votes[b.vote] = (prompt.votes[b.vote] || 0) + 1;
    writeJson(cfgPath, cfg);
    json({ ok: true, votes: prompt.votes });
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
    const strs = ['sampler','scheduler','output_subdir','negative','checkpoint_name','lora_detail_name','lora_nature_name'];
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

  // ── galeria: listar imagens ───────────────────────────────────────────────
  const mGalList = pathname.match(/^\/api\/galeria\/([^/]+)$/);
  if (mGalList && method === 'GET') {
    const catNome = mGalList[1];
    const cfg = readJson(path.join(CATEGORIAS_DIR, `${catNome}.json`));
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const subdir = cfg.output_subdir || catNome;
    const baseDir = path.join(COMFY_OUTPUT, subdir);
    const expDir  = path.join(baseDir, 'experimentos');
    const results = [];

    function scanDir(dir, isExp) {
      if (!fs.existsSync(dir)) return;
      for (const f of fs.readdirSync(dir)) {
        if (!f.endsWith('.png')) continue;
        const fp   = path.join(dir, f);
        const stat = fs.statSync(fp);
        const m    = f.match(new RegExp(`^${catNome}_(.+)_seed(\\d+)_\\d+_\\.png$`));
        results.push({
          filename: f,
          is_exp:   isExp,
          pnome:    m ? m[1] : null,
          seed:     m ? parseInt(m[2], 10) : null,
          mtime:    stat.mtime.toISOString(),
          size_kb:  Math.round(stat.size / 1024),
          meta:     parseComfyMeta(fp),
        });
      }
    }

    scanDir(baseDir, false);
    scanDir(expDir,  true);
    results.sort((a, b) => (b.mtime > a.mtime ? 1 : -1));
    json(results);
    return;
  }

  // ── galeria: servir thumbnail ─────────────────────────────────────────────
  const mGalThumb = pathname.match(/^\/api\/galeria\/([^/]+)\/thumb\/([^/]+)$/);
  if (mGalThumb && method === 'GET') {
    const catNome  = mGalThumb[1];
    const filename = mGalThumb[2];
    const cfg      = readJson(path.join(CATEGORIAS_DIR, `${catNome}.json`));
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const subdir   = cfg.output_subdir || catNome;
    const stem     = filename.replace(/\.png$/, '');
    // Procura em thumbs/ e thumbs/ dentro de experimentos/
    const candidates = [
      path.join(COMFY_OUTPUT, subdir, 'thumbs', stem + '.jpg'),
      path.join(COMFY_OUTPUT, subdir, 'experimentos', 'thumbs', stem + '.jpg'),
    ];
    const thumbPath = candidates.find(p => fs.existsSync(p));
    if (!thumbPath) { res.writeHead(404); res.end('Not found'); return; }
    const resolved = path.resolve(thumbPath);
    if (!resolved.startsWith(path.resolve(COMFY_OUTPUT) + path.sep)) {
      err('Acesso negado', 403); return;
    }
    res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Cache-Control': 'max-age=86400' });
    fs.createReadStream(resolved).pipe(res);
    return;
  }

  // ── galeria: servir imagem ────────────────────────────────────────────────
  const mGalImg = pathname.match(/^\/api\/galeria\/([^/]+)\/img\/([^/]+)$/);
  if (mGalImg && method === 'GET') {
    const catNome  = mGalImg[1];
    const filename = mGalImg[2];
    const cfg      = readJson(path.join(CATEGORIAS_DIR, `${catNome}.json`));
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const subdir   = cfg.output_subdir || catNome;
    const baseDir  = path.join(COMFY_OUTPUT, subdir);
    // Aceita arquivo direto ou dentro de experimentos/
    let imgPath = path.join(baseDir, filename);
    if (!fs.existsSync(imgPath)) imgPath = path.join(baseDir, 'experimentos', filename);
    // Segurança: garante que o path resolvido está dentro de COMFY_OUTPUT
    const resolved = path.resolve(imgPath);
    if (!resolved.startsWith(path.resolve(COMFY_OUTPUT) + path.sep)) {
      err('Acesso negado', 403); return;
    }
    if (!fs.existsSync(resolved)) { err('Imagem não encontrada', 404); return; }
    res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'max-age=3600' });
    fs.createReadStream(resolved).pipe(res);
    return;
  }

  // ── galeria: deletar imagem + thumbnail ───────────────────────────────────
  const mGalDel = pathname.match(/^\/api\/galeria\/([^/]+)\/img\/([^/]+)$/);
  if (mGalDel && method === 'DELETE') {
    const catNome  = mGalDel[1];
    const filename = decodeURIComponent(mGalDel[2]);
    const cfg      = readJson(path.join(CATEGORIAS_DIR, `${catNome}.json`));
    if (!cfg) { err('Categoria não encontrada', 404); return; }
    const subdir  = cfg.output_subdir || catNome;
    const baseDir = path.join(COMFY_OUTPUT, subdir);

    // Localiza a imagem (raiz ou experimentos/)
    let imgPath = path.join(baseDir, filename);
    let isExp   = false;
    if (!fs.existsSync(imgPath)) { imgPath = path.join(baseDir, 'experimentos', filename); isExp = true; }
    const resolved = path.resolve(imgPath);
    if (!resolved.startsWith(path.resolve(COMFY_OUTPUT) + path.sep)) { err('Acesso negado', 403); return; }
    if (!fs.existsSync(resolved)) { err('Imagem não encontrada', 404); return; }

    // Thumbnail correspondente
    const stem      = filename.replace(/\.png$/, '');
    const thumbPath = path.join(baseDir, ...(isExp ? ['experimentos', 'thumbs'] : ['thumbs']), stem + '.jpg');

    try {
      fs.unlinkSync(resolved);
      if (fs.existsSync(thumbPath)) fs.unlinkSync(thumbPath);

      // Auto-vote-down: extrai pnome do nome do arquivo e registra no prompt
      const fnMatch = filename.match(new RegExp(`^${catNome}_(.+)_seed\\d+_\\d+_\\.png$`));
      if (fnMatch) {
        const pnome   = fnMatch[1];
        const catCfg  = readJson(path.join(CATEGORIAS_DIR, `${catNome}.json`));
        const prompt  = catCfg && (catCfg.prompts || []).find(p => p.name === pnome);
        if (prompt) {
          if (!prompt.votes) prompt.votes = { up: 0, down: 0 };
          prompt.votes.down = (prompt.votes.down || 0) + 1;
          writeJson(path.join(CATEGORIAS_DIR, `${catNome}.json`), catCfg);
        }
      }

      json({ ok: true });
    } catch(e) { json({ ok: false, error: e.message }); }
    return;
  }

  res.writeHead(404); res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`\n  encena web  →  http://localhost:${PORT}\n`);
});
