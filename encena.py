#!/usr/bin/env python3
"""
encena.py — Gerador de prompts e imagens fotorrealistas.

Gerencia o ciclo completo: criar prompts com Ollama, experimentar sem
comprometer os JSONs, gerar imagens via ComfyUI, promover ou remover prompts.

AÇÕES
─────
  prompts      (pr)   Gera prompts e salva no JSON da categoria
  imagens      (im)   Gera imagens a partir dos prompts salvos
  experimentar (ex)   Gera prompts + imagens sem salvar (guarda em rascunhos)
  listar       (ls)   Lista categorias, prompts definitivos e rascunhos
  promover     (pv)   Move rascunho para o JSON definitivo
  remover      (rm)   Remove prompt do JSON definitivo
  estilos      (es)   Lista os estilos fotográficos disponíveis

EXEMPLOS
────────
  # Gerar prompts (modo auto: usa Ollama se disponível, combinatório como fallback)
  encena.py prompts -c canyon -q 5

  # Gerar com Ollama em modo livre (Ollama escolhe o cenário sem base fixo)
  encena.py prompts -c canyon -q 3 -m ollama --livre

  # Experimentar: gera prompt + imagem, salva em rascunhos para revisão
  encena.py experimentar -c canyon -q 2 --livre

  # Gerar imagens de uma categoria a partir dos prompts salvos
  encena.py imagens -c canyon -q 3

  # Gerar imagens de todas as categorias (1 imagem cada)
  encena.py imagens --todas

  # Forçar um prompt específico pelo nome ao gerar imagens
  encena.py imagens -c canyon -q 5 -pn bryce_sunrise

  # Gerar imagens de múltiplas categorias
  encena.py imagens -c "canyon,lavanda" -q 2

  # Listar tudo — categorias, prompts definitivos e rascunhos pendentes
  encena.py listar
  encena.py listar -c canyon

  # Promover rascunho para o JSON definitivo
  encena.py promover canyon_livre -c canyon
  encena.py promover todos -c canyon

  # Remover prompt do JSON definitivo
  encena.py remover bryce_sunrise -c canyon
  encena.py remover todos -c canyon       # limpa todos (pede confirmação)
"""

import argparse
import json
import random
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

# ─── Configuração ─────────────────────────────────────────────────────────────

CONFIGS_DIR = Path(__file__).parent / "categorias"
OLLAMA_URL  = "http://localhost:11434"
COMFY_URL   = "http://localhost:8188"
CLIENT_ID   = str(uuid.uuid4())

CHECKPOINT  = "DreamShaperXL_Lightning.safetensors"
LORA_DETAIL = "add-detail-xl.safetensors"
LORA_NATURE = "LoRA-NaturePhotoreal-landscapes-SDXL-v1.safetensors"
UPSCALER    = "RealESRGAN_x4plus.pth"

NEGATIVE_DEFAULT = (
    "dark, gloomy, horror, people, text, watermark, blurry, ugly, disturbing, "
    "violence, cartoon, anime, painting, illustration, drawing, 3d render, cgi, "
    "artificial, fake, overexposed, underexposed, bad composition, deformed, noise, "
    "artifacts, glitch, pixelated, compression artifacts, jpeg artifacts, distortion, "
    "splashing water, water spray, frozen water, crashing waves, sea foam, turbulent "
    "water, motion blur, buildings, urban, roads, floating objects, objects out of "
    "place, misplaced reflections, impossible reflections"
)

# ─── Dimensões combinatórias ──────────────────────────────────────────────────

BIOMAS = [
    "tropical beach", "alpine meadow", "arctic tundra", "sahara desert",
    "amazon rainforest", "scottish highlands", "patagonia steppe",
    "norwegian fjord", "icelandic lava field", "new zealand coastline",
    "japanese bamboo grove", "tuscany rolling hills", "canadian rockies",
    "mongolian steppe", "madagascar jungle",
]

HORAS = [
    "sunrise", "early morning golden hour", "midday harsh light",
    "late afternoon", "sunset golden hour", "blue hour", "starry night",
    "aurora night", "stormy overcast", "misty morning",
]

CLIMAS = [
    "crystal clear", "dramatic storm clouds approaching", "light morning mist",
    "heavy fog", "after the rain", "light snow falling", "golden dust haze",
    "rainbow visible", "dramatic cumulonimbus", "scattered clouds with light rays",
]

PERSPECTIVAS = [
    "wide establishing shot", "low angle ground level", "elevated viewpoint",
    "panoramic vista", "intimate close detail", "leading lines composition",
    "reflection shot", "silhouette shot",
]

ELEMENTOS_FOCAIS = [
    "lone tree", "ancient rock formation", "winding river", "frozen lake",
    "waterfall", "mountain peak", "flower field", "sand dunes",
    "coral reef visible", "bird in flight", "lightning bolt",
    "sunbeam through clouds",
]

TEMPLATE = (
    "{abertura} professional nature photography, {bioma} at {hora}, "
    "{clima}, {perspectiva}, {elemento_focal}, "
    "{captura}, ultra realistic, National Geographic"
)

# ─── Estilos fotográficos ─────────────────────────────────────────────────────
# Cada estilo encapsula abertura + câmera + lente + configuração técnica.
# O usuário escolhe pelo resultado desejado, sem precisar saber os parâmetros.

ESTILOS_FOTO: dict[str, dict[str, str]] = {
    "padrao": {
        "descricao": "DSLR versátil, tudo nítido — bom ponto de partida geral",
        "abertura":  "RAW photo,",
        "captura":   "Canon EOS R5, 24-70mm f/2.8, f/8, ISO 100",
    },
    "ultrawide": {
        "descricao": "Grande angular extremo — céu enorme, perspectiva imersiva e dramática",
        "abertura":  "RAW photo,",
        "captura":   "Canon EOS R5, 16-35mm f/2.8, f/11, ISO 100",
    },
    "telefoto": {
        "descricao": "Telefoto — sujeito isolado, fundo comprimido e desfocado (bokeh)",
        "abertura":  "RAW photo,",
        "captura":   "Sony A7R V, 400mm f/2.8, f/4, ISO 400",
    },
    "medioformato": {
        "descricao": "Médio formato — detalhe extraordinário, 'pop 3D', dinâmica extrema",
        "abertura":  "medium format RAW capture,",
        "captura":   "Hasselblad X2D, 45mm f/3.5, f/8, ISO 64",
    },
    "noturno": {
        "descricao": "Noturno — abertura máxima, grain atmosférico de ISO alto",
        "abertura":  "RAW photo,",
        "captura":   "Sony A7R V, 24mm f/1.4, f/2, ISO 3200",
    },
    "longaexposicao": {
        "descricao": "Longa exposição — água e nuvens sedosas, 30s com tripé e filtro ND",
        "abertura":  "RAW photo,",
        "captura":   "Canon EOS R5, 24mm f/11, 30s long exposure, ISO 100, ND filter",
    },
    "analogico": {
        "descricao": "Scan de filme analógico — paleta orgânica quente, grão de película",
        "abertura":  "analog film photograph,",
        "captura":   "Hasselblad medium format, Kodak Portra 400 film scan",
    },
    "aereo": {
        "descricao": "Drone — perspectiva aérea de cima, tudo nítido do primeiro plano ao horizonte",
        "abertura":  "aerial drone RAW photograph,",
        "captura":   "DJI Mavic 3 Pro, 24mm equivalent, f/8, ISO 100",
    },
}

# ─── Temas por categoria ──────────────────────────────────────────────────────
# Biomas e elementos temáticos por categoria.
# Categorias sem tema definido usam os pools globais como fallback.

TEMAS: dict[str, dict[str, list[str]]] = {
    "canyon": {
        "biomas": [
            "arizona slot canyon", "grand canyon south rim", "bryce canyon hoodoos",
            "zion narrow canyon", "antelope canyon arizona", "utah red rock desert",
            "canyonlands mesa arch", "escalante canyon utah",
        ],
        "elementos": [
            "narrow sandstone walls", "rock arch formation", "canyon river bend",
            "desert hoodoo spires", "canyon rim overlook", "beam of light through slot canyon",
            "ancient petroglyphs on rock wall", "dry desert riverbed",
        ],
    },
    "aurora_boreal": {
        "biomas": [
            "iceland arctic wilderness", "norway tromsø fjord", "alaska yukon tundra",
            "lapland finland snowscape", "greenland ice sheet", "canadian yukon boreal forest",
            "svalbard polar landscape", "faroe islands coastline",
        ],
        "elementos": [
            "aurora borealis curtains", "frozen lake reflecting aurora",
            "snow-covered pine forest silhouette", "northern lights over mountain peak",
            "aurora over wooden cabin", "star-filled polar sky",
            "milky way with aurora", "icy tundra under aurora glow",
        ],
    },
    "floresta_bambu": {
        "biomas": [
            "arashiyama bamboo grove japan", "chinese bamboo forest",
            "tropical bamboo jungle asia", "yunnan bamboo highlands china",
            "sagano bamboo forest kyoto",
        ],
        "elementos": [
            "dense bamboo stalks", "dappled light through bamboo canopy",
            "stone path through bamboo", "mist between bamboo trunks",
            "single bamboo leaf close-up", "bamboo grove curving tunnel",
        ],
    },
    "lago_alpino": {
        "biomas": [
            "swiss alps lake shore", "dolomites mountain lake", "patagonia glacial lake",
            "rocky mountain alpine tarn", "norwegian mountain lake",
            "austrian alps lake", "new zealand southern alps lake",
        ],
        "elementos": [
            "mirror reflection of mountain peaks in lake", "alpine meadow meeting lake shore",
            "crystal clear glacial water", "granite boulders at lake edge",
            "snow-capped peak reflected in still water", "wildflowers at alpine lake margin",
        ],
    },
    "lavanda": {
        "biomas": [
            "provence lavender fields france", "valensole plateau france",
            "brihuega lavender spain", "tuscany lavender countryside",
            "sequim washington lavender farm", "hokkaido lavender japan",
        ],
        "elementos": [
            "endless rows of purple lavender", "lavender field with stone farmhouse",
            "bee on lavender bloom", "lavender field horizon at sunset",
            "single lavender sprig close-up", "lavender rows converging to vanishing point",
        ],
    },
    "praia_por_do_sol": {
        "biomas": [
            "tropical caribbean beach", "hawaii volcanic coastline",
            "maldives white sand beach", "thai islands beach",
            "brazilian golden coast", "mediterranean greek island beach",
            "indonesian bali sunset beach",
        ],
        "elementos": [
            "golden sunset reflection on wet sand", "silhouette of palm trees at sunset",
            "calm ocean horizon at golden hour", "tide pools with warm light",
            "gentle waves at sunset", "coconut palm leaning over water",
            "dramatic orange and pink sky over sea",
        ],
    },
}

# ─── Utilitários ──────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def make_name(base_a: str, base_b: str, existentes: set[str]) -> str:
    base = f"{slugify(base_a)[:20]}_{slugify(base_b)[:15]}"
    nome, contador = base, 2
    while nome in existentes:
        nome = f"{base}_{contador}"
        contador += 1
    return nome

# ─── JSON e rascunhos ─────────────────────────────────────────────────────────

def carregar_json(categoria: str) -> dict:
    path = CONFIGS_DIR / f"{categoria}.json"
    if not path.exists():
        print(f"ERRO: {path} não encontrado.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def salvar_json(categoria: str, dados: dict):
    path = CONFIGS_DIR / f"{categoria}.json"
    with open(path, "w") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
        f.write("\n")


def listar_categorias() -> list[str]:
    return sorted(
        p.stem for p in CONFIGS_DIR.glob("*.json")
        if not p.stem.endswith("_rascunhos")
    )


def carregar_rascunhos(categoria: str) -> list[dict]:
    path = CONFIGS_DIR / f"{categoria}_rascunhos.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def salvar_rascunhos(categoria: str, rascunhos: list[dict]):
    path = CONFIGS_DIR / f"{categoria}_rascunhos.json"
    if not rascunhos:
        path.unlink(missing_ok=True)
        return
    with open(path, "w") as f:
        json.dump(rascunhos, f, indent=2, ensure_ascii=False)
        f.write("\n")


def adicionar_rascunho(categoria: str, entrada: dict):
    rascunhos = carregar_rascunhos(categoria)
    if not any(r["name"] == entrada["name"] for r in rascunhos):
        rascunhos.append(entrada)
        salvar_rascunhos(categoria, rascunhos)

# ─── Ollama ───────────────────────────────────────────────────────────────────

def _ollama_get(path: str) -> dict:
    with urllib.request.urlopen(f"{OLLAMA_URL}{path}", timeout=5) as r:
        return json.loads(r.read())


def _ollama_post(path: str, dados: dict, timeout: int = 120) -> dict:
    body = json.dumps(dados).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}{path}", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_disponivel() -> bool:
    try:
        _ollama_get("/api/tags")
        return True
    except Exception:
        return False


def ollama_escolher_modelo() -> str | None:
    """Prefere mistral:7b, depois mistral:latest, depois qualquer mistral, depois o primeiro disponível."""
    try:
        dados = _ollama_get("/api/tags")
        modelos = [m["name"] for m in dados.get("models", [])]
        if not modelos:
            return None
        for preferido in ("mistral:7b", "mistral:latest"):
            if preferido in modelos:
                return preferido
        for m in modelos:
            if "mistral" in m.lower():
                return m
        return modelos[0]
    except Exception:
        return None


def ollama_refinar(base: str, modelo: str, categoria: str | None = None) -> str:
    """Reescreve um prompt base com mais detalhes. Mantém o tema da categoria."""
    dica_tema = (
        f" The scene must belong to the '{categoria}' category — "
        "keep all details thematically consistent with this theme."
    ) if categoria else ""
    mensagem = (
        "Rewrite this nature photography prompt with more specific, evocative details "
        f"about light, texture, atmosphere and geography.{dica_tema} "
        "Return ONLY the improved prompt — no explanation, no quotes, no extra lines.\n\n"
        f"{base}"
    )
    try:
        resp = _ollama_post("/api/generate", {
            "model": modelo, "prompt": mensagem, "stream": False,
            "system": (
                "You are an expert Stable Diffusion XL prompt engineer specialising in "
                "photorealistic nature photography. Always start responses with "
                "'RAW photo, professional nature photography,' and end with "
                "'Canon EOS R5, f/8, ultra realistic, National Geographic'."
            ),
        })
        texto = resp.get("response", "").strip()
        if texto:
            return texto
    except Exception as e:
        print(f"  [ollama] erro ao refinar: {e} — usando combinatório", flush=True)
    return base


def ollama_livre(categoria: str, modelo: str, captura: str, abertura: str) -> str:
    """Ollama escolhe o cenário completo sem base fixo."""
    mensagem = (
        f"Create an original Stable Diffusion XL prompt for a '{categoria}' landscape photography scene. "
        "You are free to choose any real location in the world that fits this theme — "
        "explore lesser-known or surprising places, not just the obvious ones. "
        "Be specific: name the exact location, describe light quality, textures, atmosphere, "
        "colors and composition. "
        "Return ONLY the prompt — no explanation, no quotes, no extra lines."
    )
    try:
        resp = _ollama_post("/api/generate", {
            "model": modelo, "prompt": mensagem, "stream": False,
            "system": (
                "You are an expert Stable Diffusion XL prompt engineer specialising in "
                "photorealistic nature and landscape photography. You have deep geographical "
                "knowledge and always pick specific, real locations with evocative visual details. "
                f"Always start responses with '{abertura} professional nature photography,' "
                f"and end with '{captura}, ultra realistic, National Geographic'."
            ),
        })
        texto = resp.get("response", "").strip()
        if texto:
            return texto
    except Exception as e:
        print(f"  [ollama] erro no modo livre: {e}", flush=True)
    return ""

# ─── ComfyUI ──────────────────────────────────────────────────────────────────

def _comfy_post(endpoint: str, dados: dict) -> dict:
    body = json.dumps(dados).encode()
    req = urllib.request.Request(
        f"{COMFY_URL}/{endpoint}", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _comfy_get(endpoint: str) -> dict:
    with urllib.request.urlopen(f"{COMFY_URL}/{endpoint}", timeout=30) as r:
        return json.loads(r.read())


def comfy_disponivel() -> bool:
    try:
        _comfy_get("system_stats")
        return True
    except Exception:
        return False


def comfy_montar_workflow(cfg: dict, positivo: str, negativo: str,
                          prefixo: str, seed: int) -> dict:
    """
    Grafo ComfyUI:
      1  CheckpointLoader
      2  LoraLoader (add-detail-xl)
      3  LoraLoader (nature-landscapes)
      4  CLIPTextEncode positivo
      5  CLIPTextEncode negativo
      6  EmptyLatentImage
      7  KSampler
      8  VAEDecode
      9  UpscaleModelLoader
      10 ImageUpscaleWithModel
      11 SaveImage
    """
    return {
        "1":  {"class_type": "CheckpointLoaderSimple",
               "inputs": {"ckpt_name": CHECKPOINT}},
        "2":  {"class_type": "LoraLoader",
               "inputs": {"model": ["1", 0], "clip": ["1", 1],
                          "lora_name": LORA_DETAIL,
                          "strength_model": cfg.get("lora_detail", 0.6),
                          "strength_clip":  cfg.get("lora_detail", 0.6)}},
        "3":  {"class_type": "LoraLoader",
               "inputs": {"model": ["2", 0], "clip": ["2", 1],
                          "lora_name": LORA_NATURE,
                          "strength_model": cfg["lora_nature"],
                          "strength_clip":  cfg["lora_nature"]}},
        "4":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": positivo, "clip": ["3", 1]}},
        "5":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": negativo, "clip": ["3", 1]}},
        "6":  {"class_type": "EmptyLatentImage",
               "inputs": {"width": cfg.get("width", 768),
                          "height": cfg.get("height", 1344),
                          "batch_size": 1}},
        "7":  {"class_type": "KSampler",
               "inputs": {"model": ["3", 0], "positive": ["4", 0],
                          "negative": ["5", 0], "latent_image": ["6", 0],
                          "seed": seed, "steps": cfg.get("steps", 8),
                          "cfg": cfg["cfg"],
                          "sampler_name": cfg.get("sampler", "dpmpp_2m_sde"),
                          "scheduler":    cfg.get("scheduler", "karras"),
                          "denoise": 1.0}},
        "8":  {"class_type": "VAEDecode",
               "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9":  {"class_type": "UpscaleModelLoader",
               "inputs": {"model_name": UPSCALER}},
        "10": {"class_type": "ImageUpscaleWithModel",
               "inputs": {"upscale_model": ["9", 0], "image": ["8", 0]}},
        "11": {"class_type": "SaveImage",
               "inputs": {"images": ["10", 0], "filename_prefix": prefixo}},
    }


def comfy_enfileirar(workflow: dict) -> str:
    resultado = _comfy_post("prompt", {"prompt": workflow, "client_id": CLIENT_ID})
    return resultado["prompt_id"]


def comfy_aguardar(prompt_id: str, tag: str) -> bool:
    inicio = time.time()
    pontos = 0
    print(f"  {tag} | enviado...", flush=True)
    while True:
        try:
            historico = _comfy_get(f"history/{prompt_id}")
        except Exception as e:
            print(f"\n  {tag} | erro: {e}", flush=True)
            time.sleep(3)
            continue

        if prompt_id in historico:
            status = historico[prompt_id].get("status", {}).get("status_str", "")
            if status == "success":
                elapsed = time.time() - inicio
                arquivos = [
                    img.get("filename", "")
                    for node in historico[prompt_id].get("outputs", {}).values()
                    for img in node.get("images", [])
                ]
                print(f"\r  {tag} | PRONTA em {elapsed:.0f}s{' ' * 10}", flush=True)
                for arq in arquivos:
                    print(f"    -> output/{arq}", flush=True)
                return True
            elif status == "error":
                msgs = historico[prompt_id].get("status", {}).get("messages", [])
                print(f"\n  {tag} | ERRO: {msgs}", flush=True)
                return False

        try:
            fila = _comfy_get("queue")
            rodando = [item[1] for item in fila.get("queue_running", [])]
            pendente = [item[1] for item in fila.get("queue_pending", [])]
            elapsed = time.time() - inicio
            if prompt_id in rodando:
                pontos = (pontos + 1) % 4
                print(f"\r  {tag} | gerando{'.' * (pontos + 1)}{' ' * (3 - pontos)} {elapsed:.0f}s",
                      end="", flush=True)
            elif prompt_id in pendente:
                pos = pendente.index(prompt_id) + 1
                print(f"\r  {tag} | fila pos {pos} — {elapsed:.0f}s  ", end="", flush=True)
        except Exception:
            pass
        time.sleep(2)

# ─── Geração de prompts ───────────────────────────────────────────────────────

def resolver_estilo(estilo: str | None) -> tuple[str, str, str]:
    """Retorna (chave, abertura, captura). Sorteia aleatoriamente se estilo for None."""
    chave = estilo or random.choice(list(ESTILOS_FOTO.keys()))
    cfg = ESTILOS_FOTO[chave]
    return chave, cfg["abertura"], cfg["captura"]


def sortear_elementos(
    categoria: str | None,
    bioma: str | None, hora: str | None, clima: str | None,
    perspectiva: str | None, elemento: str | None,
    abertura: str, captura: str,
) -> dict:
    tema = TEMAS.get(categoria or "", {})
    return {
        "abertura":       abertura,
        "bioma":          bioma       or random.choice(tema.get("biomas",    BIOMAS)),
        "hora":           hora        or random.choice(HORAS),
        "clima":          clima       or random.choice(CLIMAS),
        "perspectiva":    perspectiva or random.choice(PERSPECTIVAS),
        "elemento_focal": elemento    or random.choice(tema.get("elementos", ELEMENTOS_FOCAIS)),
        "captura":        captura,
    }


def _resolver_modelo(modo: str, livre: bool) -> str | None:
    """Resolve o modelo Ollama conforme o modo. Encerra se modo=ollama e serviço indisponível."""
    if modo == "combinatorio":
        print("  Modo: combinatório")
        return None
    if ollama_disponivel():
        modelo = ollama_escolher_modelo()
        if modelo:
            rotulo = f"ollama livre ({modelo})" if livre else f"ollama ({modelo})"
            print(f"  Modo: {rotulo}")
            return modelo
        print("  Ollama sem modelos instalados — usando combinatório")
        return None
    if modo == "ollama":
        print(f"ERRO: Ollama não acessível em {OLLAMA_URL}")
        sys.exit(1)
    print("  Ollama indisponível — usando combinatório")
    return None


def _gerar_um_prompt(
    i: int, total: int,
    categoria: str, modelo: str | None, livre: bool,
    bioma: str | None, hora: str | None, clima: str | None,
    perspectiva: str | None, elemento: str | None,
    existentes: set[str],
    estilo: str | None = None,
) -> tuple[str, str]:
    """Gera um único (nome, texto) de prompt."""
    estilo_chave, abertura, captura = resolver_estilo(estilo)
    descricao_estilo = ESTILOS_FOTO[estilo_chave]["descricao"]

    if livre and modelo:
        texto = ollama_livre(categoria, modelo, captura, abertura)
        if not texto:  # fallback se Ollama falhar
            elementos = sortear_elementos(categoria, bioma, hora, clima, perspectiva, elemento, abertura, captura)
            texto = TEMPLATE.format(**elementos)
        nome = make_name(categoria, "livre", existentes)
        print(f"\n  [{i + 1}/{total}] {nome}")
    else:
        elementos = sortear_elementos(categoria, bioma, hora, clima, perspectiva, elemento, abertura, captura)
        base = TEMPLATE.format(**elementos)
        texto = ollama_refinar(base, modelo, categoria) if modelo else base
        nome = make_name(elementos["bioma"], elementos["hora"], existentes)
        print(f"\n  [{i + 1}/{total}] {nome}")
        print(f"  elementos : {elementos['bioma']} | {elementos['hora']} | {elementos['clima']}")
    print(f"  estilo    : {estilo_chave} — {descricao_estilo}")
    print(f"  prompt    : {texto[:100]}{'...' if len(texto) > 100 else ''}")
    return nome, texto

# ─── Ações ────────────────────────────────────────────────────────────────────

def cmd_listar(categoria: str | None):
    categorias = [categoria] if categoria else listar_categorias()
    for cat in categorias:
        dados = carregar_json(cat)
        prompts = dados.get("prompts", [])
        rascunhos = carregar_rascunhos(cat)
        n_def = len(prompts)
        n_rasc = len(rascunhos)
        print(f"\n{'─' * 64}")
        print(f"  {cat}  ({n_def} definitivo{'s' if n_def != 1 else ''}  |  {n_rasc} rascunho{'s' if n_rasc != 1 else ''})")
        print(f"{'─' * 64}")
        if prompts:
            for p in prompts:
                print(f"  {p['name']}")
                print(f"    {p['text'][:72].replace(chr(10), ' ')}...")
        else:
            print("  (nenhum prompt definitivo)")
        if rascunhos:
            print(f"\n  ── Rascunhos pendentes (use 'promover' para salvar) ──")
            for r in rascunhos:
                print(f"  [R] {r['name']}")
                print(f"      {r['text'][:72].replace(chr(10), ' ')}...")

    print(f"\n{'─' * 64}")
    # Mostra combinações reais por categoria listada, ou o global se listou todas
    cats_listadas = [categoria] if categoria else listar_categorias()
    if len(cats_listadas) == 1:
        cat = cats_listadas[0]
        tema = TEMAS.get(cat, {})
        n_biomas    = len(tema.get("biomas",    BIOMAS))
        n_elementos = len(tema.get("elementos", ELEMENTOS_FOCAIS))
        combos = n_biomas * len(HORAS) * len(CLIMAS) * len(PERSPECTIVAS) * n_elementos
        tem_tema = cat in TEMAS
        rotulo = f"'{cat}'" + (" (pools temáticos)" if tem_tema else " (pools globais)")
        print(f"  Combinações disponíveis para {rotulo}: {combos:,}")
        print(f"  ({n_biomas} biomas × {len(HORAS)} horas × {len(CLIMAS)} climas"
              f" × {len(PERSPECTIVAS)} perspectivas × {n_elementos} elementos)")
    else:
        combos_global = (len(BIOMAS) * len(HORAS) * len(CLIMAS)
                         * len(PERSPECTIVAS) * len(ELEMENTOS_FOCAIS))
        print(f"  Combinações globais disponíveis: {combos_global:,}")
        print(f"  ({len(BIOMAS)} biomas × {len(HORAS)} horas × {len(CLIMAS)} climas"
              f" × {len(PERSPECTIVAS)} perspectivas × {len(ELEMENTOS_FOCAIS)} elementos)")
        tematizadas = [c for c in cats_listadas if c in TEMAS]
        if tematizadas:
            print(f"  Categorias com pools temáticos (combinações menores): {', '.join(tematizadas)}")
            print(f"  Use 'listar -c CATEGORIA' para ver o número exato de cada uma.")
    print()


def cmd_prompts(
    categoria: str, quantidade: int, modo: str, livre: bool,
    bioma: str | None, hora: str | None, clima: str | None,
    perspectiva: str | None, elemento: str | None,
    simular: bool, estilo: str | None,
):
    dados = carregar_json(categoria)
    existentes: set[str] = {p["name"] for p in dados.get("prompts", [])}

    if livre and modo == "combinatorio":
        print("  Aviso: --livre ignorado com --modo combinatorio (requer Ollama)")

    modelo = _resolver_modelo(modo, livre)
    novos: list[dict] = []

    for i in range(quantidade):
        nome, texto = _gerar_um_prompt(
            i, quantidade, categoria, modelo, livre,
            bioma, hora, clima, perspectiva, elemento, existentes, estilo,
        )
        existentes.add(nome)
        novos.append({"name": nome, "text": texto})

    if simular:
        print("\n  [simulação] nenhuma alteração salva.")
        return

    dados["prompts"].extend(novos)
    salvar_json(categoria, dados)
    print(f"\n  {len(novos)} prompt(s) adicionado(s) → {categoria}.json  "
          f"({len(dados['prompts'])} total)")


def cmd_imagens(
    categorias: list[str], quantidade: int, prompt_nome: str | None,
):
    jobs = [(cat, carregar_json(cat)) for cat in categorias]
    total = len(jobs) * quantidade

    print("=" * 70)
    print(f"  {len(jobs)} categoria(s) × {quantidade} imagem(ns) = {total} total")
    print(f"  Checkpoint : {CHECKPOINT}")
    print(f"  LoRAs      : {LORA_DETAIL}  +  {LORA_NATURE}")
    print(f"  Upscaler   : {UPSCALER}  |  Formato: 768×1344")
    print("=" * 70)
    for cat, cfg in jobs:
        n = len(cfg.get("prompts", []))
        print(f"  • {cat:24s}  cfg={cfg['cfg']}  nature={cfg['lora_nature']}  {n} prompts")
    print()

    if not comfy_disponivel():
        print(f"ERRO: ComfyUI não acessível em {COMFY_URL}")
        sys.exit(1)
    print("  ComfyUI: conectado\n")

    def selecionar_prompts(cfg: dict, n: int, nome: str | None) -> list[tuple[str, str]]:
        prompts = cfg.get("prompts", [])
        if not prompts:
            print(f"ERRO: categoria '{cfg.get('category', '?')}' não tem prompts.")
            sys.exit(1)
        if nome:
            match = next((p for p in prompts if p["name"] == nome), None)
            if not match:
                print(f"ERRO: prompt '{nome}' não encontrado.")
                print(f"  Disponíveis: {[p['name'] for p in prompts]}")
                sys.exit(1)
            return [(match["name"], match["text"])] * n
        resultado: list[tuple[str, str]] = []
        pool = prompts.copy()
        while len(resultado) < n:
            random.shuffle(pool)
            resultado.extend((p["name"], p["text"]) for p in pool)
        return resultado[:n]

    fila: list[tuple[str, str]] = []
    idx = 0
    for cat, cfg in jobs:
        negativo = cfg.get("negative", NEGATIVE_DEFAULT)
        subdir = cfg.get("output_subdir", f"landscapes/{cat}")
        for pnome, ptexto in selecionar_prompts(cfg, quantidade, prompt_nome):
            seed = random.randint(1, 2**32 - 1)
            prefixo = f"{subdir}/{cat}_{pnome}_seed{seed}"
            tag = f"[{idx + 1:02d}/{total}] {cat} / {pnome}"
            wf = comfy_montar_workflow(cfg, ptexto, negativo, prefixo, seed)
            pid = comfy_enfileirar(wf)
            fila.append((pid, tag))
            print(f"  Enfileirado {tag} | seed={seed} | id={pid[:8]}...")
            idx += 1
            time.sleep(0.3)

    print()
    sucessos = sum(comfy_aguardar(pid, tag) for pid, tag in fila)
    print()
    print("=" * 70)
    print(f"  Concluído: {sucessos}/{total} imagens")
    print(f"  Local    : ~/ComfyUI/output/landscapes/")
    print("=" * 70)


def cmd_experimentar(
    categoria: str, quantidade: int, modo: str, livre: bool,
    bioma: str | None, hora: str | None, clima: str | None,
    perspectiva: str | None, elemento: str | None,
    estilo: str | None,
):
    dados = carregar_json(categoria)
    existentes: set[str] = (
        {p["name"] for p in dados.get("prompts", [])}
        | {r["name"] for r in carregar_rascunhos(categoria)}
    )

    if not comfy_disponivel():
        print(f"ERRO: ComfyUI não acessível em {COMFY_URL}")
        sys.exit(1)

    modelo = _resolver_modelo(modo, livre)
    negativo = dados.get("negative", NEGATIVE_DEFAULT)
    subdir = dados.get("output_subdir", f"landscapes/{categoria}")
    print(f"  ComfyUI: conectado — saída em output/{subdir}/experimentos/\n")

    novos: list[dict] = []
    for i in range(quantidade):
        nome, texto = _gerar_um_prompt(
            i, quantidade, categoria, modelo, livre,
            bioma, hora, clima, perspectiva, elemento, existentes, estilo,
        )
        existentes.add(nome)

        seed = random.randint(1, 2**32 - 1)
        prefixo = f"{subdir}/experimentos/{nome}_seed{seed}"
        wf = comfy_montar_workflow(dados, texto, negativo, prefixo, seed)
        pid = comfy_enfileirar(wf)
        comfy_aguardar(pid, f"[{i + 1}/{quantidade}] {nome}")

        adicionar_rascunho(categoria, {"name": nome, "text": texto})
        print(f"  Salvo em rascunhos: {nome}")
        novos.append({"name": nome, "text": texto})

    n_rasc = len(carregar_rascunhos(categoria))
    print(f"\n  {len(novos)} imagem(ns) gerada(s)  |  {n_rasc} rascunho(s) pendente(s)")
    if novos:
        print(f"  Promover um:    encena.py promover {novos[0]['name']} -c {categoria}")
        print(f"  Promover todos: encena.py promover todos -c {categoria}")


def cmd_promover(categoria: str, nome: str):
    rascunhos = carregar_rascunhos(categoria)
    if not rascunhos:
        print(f"  Nenhum rascunho pendente em '{categoria}'.")
        sys.exit(1)

    alvos = rascunhos if nome == "todos" else [r for r in rascunhos if r["name"] == nome]
    if not alvos:
        print(f"ERRO: rascunho '{nome}' não encontrado.")
        print(f"  Disponíveis: {[r['name'] for r in rascunhos]}")
        sys.exit(1)

    dados = carregar_json(categoria)
    existentes = {p["name"] for p in dados["prompts"]}
    adicionados = []
    for entrada in alvos:
        if entrada["name"] in existentes:
            print(f"  Ignorado (já existe): {entrada['name']}")
            continue
        dados["prompts"].append(entrada)
        adicionados.append(entrada["name"])

    salvar_json(categoria, dados)
    promovidos = {e["name"] for e in alvos}
    salvar_rascunhos(categoria, [r for r in rascunhos if r["name"] not in promovidos])

    for n in adicionados:
        print(f"  Promovido → {categoria}.json : {n}")
    restantes = len(rascunhos) - len(alvos)
    print(f"  Rascunhos restantes: {restantes}" if restantes else "  Rascunhos limpos.")


def cmd_remover(categoria: str, nome: str):
    dados = carregar_json(categoria)
    prompts = dados.get("prompts", [])

    if nome == "todos":
        if not prompts:
            print(f"  Nenhum prompt em '{categoria}'.")
            sys.exit(1)
        print(f"  Atenção: remover TODOS os {len(prompts)} prompts de '{categoria}'.")
        print("  Digite 'sim' para confirmar: ", end="", flush=True)
        if input().strip().lower() != "sim":
            print("  Cancelado.")
            sys.exit(0)
        dados["prompts"] = []
        salvar_json(categoria, dados)
        print(f"  {len(prompts)} prompt(s) removido(s) de {categoria}.json")
        return

    match = next((p for p in prompts if p["name"] == nome), None)
    if not match:
        print(f"ERRO: prompt '{nome}' não encontrado em '{categoria}'.")
        print(f"  Disponíveis: {[p['name'] for p in prompts]}")
        sys.exit(1)

    dados["prompts"] = [p for p in prompts if p["name"] != nome]
    salvar_json(categoria, dados)
    print(f"  Removido de {categoria}.json : {nome}")
    print(f"  Prompts restantes: {len(dados['prompts'])}")

# ─── CLI ──────────────────────────────────────────────────────────────────────

def _sub(subparsers, nome, aliases, descricao_curta, descricao_longa, exemplos=""):
    """Cria um subparser com padrão consistente de ajuda."""
    epilog = f"Exemplos:\n{exemplos}" if exemplos else ""
    return subparsers.add_parser(
        nome,
        aliases=aliases,
        help=descricao_curta,
        description=descricao_longa,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )


def _arg_ajuda(p):
    p.add_argument("--ajuda", "-h", action="help", help="Mostra esta ajuda e encerra")


def _arg_categoria(p, obrigatorio=True, multi=False):
    ajuda = "Categoria alvo (ex: canyon, aurora_boreal)"
    if multi:
        ajuda += ". Aceita lista separada por vírgula: 'canyon,lavanda'"
    p.add_argument("--categoria", "-c", metavar="CAT",
                   required=obrigatorio, help=ajuda)


def _args_prompt(p):
    """Argumentos comuns a prompts e experimentar."""
    p.add_argument("--quantidade", "-q", type=int, default=3,
                   help="Quantidade de prompts a gerar (default: 3)")
    p.add_argument("--modo", "-m",
                   choices=["auto", "combinatorio", "ollama"], default="auto",
                   help="auto: usa Ollama se disponível, senão combinatório (default)\n"
                        "combinatorio: sorteia elementos das listas curadas, sem Ollama\n"
                        "ollama: requer Ollama ativo, encerra se indisponível")
    p.add_argument("--livre", "-lv", action="store_true",
                   help="Ollama escolhe o cenário livremente, sem base combinatório.\n"
                        "Produz mais variedade e surpresas. Requer --modo ollama ou auto.")
    estilos = list(ESTILOS_FOTO.keys())
    p.add_argument("--estilo", "-e", choices=estilos, metavar="ESTILO",
                   help="Estilo fotográfico. Sorteia aleatoriamente se omitido.\n"
                        f"Opções: {', '.join(estilos)}\n"
                        "Use 'encena.py estilos' para ver descrições completas.")
    p.add_argument("--bioma",       metavar="TEXTO",
                   help="Força bioma específico (ex: 'patagonia steppe')")
    p.add_argument("--hora",        metavar="TEXTO",
                   help="Força hora do dia (ex: 'golden hour', 'blue hour')")
    p.add_argument("--clima",       metavar="TEXTO",
                   help="Força condição climática (ex: 'heavy fog')")
    p.add_argument("--perspectiva", metavar="TEXTO",
                   help="Força perspectiva (ex: 'low angle ground level')")
    p.add_argument("--elemento",    metavar="TEXTO",
                   help="Força elemento focal (ex: 'lone tree')")


class _Parser(argparse.ArgumentParser):
    """ArgumentParser com mensagem de erro amigável para ação inválida."""
    def error(self, message: str):
        if "invalid choice" in message and "AÇÃO" in message:
            acao = sys.argv[1] if len(sys.argv) > 1 else "?"
            print(f"\n  '{acao}' não é uma ação válida.\n")
            print("  Ações disponíveis:\n")
            acoes = [
                ("prompts",      "pr",     "Gera prompts e salva no JSON da categoria"),
                ("imagens",      "im",     "Gera imagens a partir dos prompts salvos"),
                ("experimentar", "ex",     "Gera prompts + imagens sem salvar (guarda em rascunhos)"),
                ("listar",       "ls",     "Lista categorias, prompts e rascunhos"),
                ("promover",     "pv",     "Move rascunho para o JSON definitivo"),
                ("remover",      "rm",     "Remove prompt do JSON definitivo"),
                ("estilos",      "es",     "Lista os estilos fotográficos disponíveis"),
            ]
            for nome, alias, desc in acoes:
                print(f"    {nome:<14} ({alias})   {desc}")
            print(f"\n  Ajuda de uma ação específica : encena.py AÇÃO --ajuda")
            print(f"  Ajuda geral                  : encena.py --ajuda\n")
            sys.exit(1)
        # outros erros: comportamento padrão
        super().error(message)


def main():
    parser = _Parser(
        prog="encena.py",
        description=(
            "Gerador de prompts e imagens fotorrealistas via Ollama + ComfyUI.\n\n"
            "Use 'encena.py AÇÃO --ajuda' para ajuda detalhada de cada ação."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        epilog=(
            "Ações disponíveis:\n"
            "  prompts      Gera prompts e salva no JSON da categoria\n"
            "  imagens      Gera imagens a partir dos prompts salvos\n"
            "  experimentar Gera prompts + imagens sem salvar (guarda em rascunhos)\n"
            "  listar       Lista categorias, prompts definitivos e rascunhos\n"
            "  promover     Move rascunho para o JSON definitivo\n"
            "  remover      Remove prompt do JSON definitivo\n"
            "  estilos      Lista os estilos fotográficos disponíveis\n"
        ),
    )
    parser.add_argument("--ajuda", "-h", action="help",
                        help="Mostra esta mensagem e encerra")

    sub = parser.add_subparsers(dest="acao", metavar="AÇÃO")

    # ── prompts ────────────────────────────────────────────────────────────────
    p_pr = _sub(sub, "prompts", ["pr"],
        "Gera prompts e salva no JSON da categoria",
        "Gera novos prompts (via Ollama ou combinatório) e salva no JSON da categoria.\n"
        "Use --simular para visualizar sem salvar.",
        exemplos=(
            "  encena.py prompts -c canyon -q 5\n"
            "  encena.py prompts -c canyon -q 3 -m ollama --livre\n"
            "  encena.py prompts -c canyon -q 3 --estilo medioformato\n"
            "  encena.py prompts -c canyon -q 3 --simular\n"
            "  encena.py prompts -c canyon -q 2 --bioma 'zion narrow canyon' --hora sunrise\n"
        ),
    )
    _arg_ajuda(p_pr)
    _arg_categoria(p_pr)
    _args_prompt(p_pr)
    p_pr.add_argument("--simular", "-s", action="store_true",
                      help="Gera e exibe os prompts sem salvar no JSON (dry-run)")

    # ── imagens ────────────────────────────────────────────────────────────────
    p_im = _sub(sub, "imagens", ["im"],
        "Gera imagens a partir dos prompts salvos no JSON",
        "Lê os prompts do JSON da categoria e envia para o ComfyUI gerar as imagens.\n"
        "Os prompts são embaralhados e ciclados para máxima variedade.",
        exemplos=(
            "  encena.py imagens -c canyon -q 3\n"
            "  encena.py imagens -c canyon -q 5 --prompt-nome bryce_sunrise\n"
            "  encena.py imagens -c 'canyon,lavanda' -q 2\n"
            "  encena.py imagens --todas -q 1\n"
        ),
    )
    _arg_ajuda(p_im)
    _arg_categoria(p_im, obrigatorio=False, multi=True)
    p_im.add_argument("--todas", "-t", action="store_true",
                      help="Processa todas as categorias disponíveis")
    p_im.add_argument("--quantidade", "-q", type=int, default=1,
                      help="Imagens por categoria (default: 1)")
    p_im.add_argument("--prompt-nome", "-pn", metavar="NOME",
                      help="Força um prompt específico pelo nome.\n"
                           "Use 'encena.py listar -c CATEGORIA' para ver os nomes.")

    # ── experimentar ──────────────────────────────────────────────────────────
    p_ex = _sub(sub, "experimentar", ["ex"],
        "Gera prompts + imagens sem salvar no JSON (guarda em rascunhos)",
        "Gera prompts e envia para o ComfyUI sem comprometer o JSON definitivo.\n"
        "Os prompts ficam em rascunhos para revisão.\n"
        "Use 'promover' para mover os aprovados para o JSON.",
        exemplos=(
            "  encena.py experimentar -c canyon -q 2 --livre\n"
            "  encena.py experimentar -c aurora_boreal -q 3 --estilo noturno\n"
            "  encena.py experimentar -c lavanda -q 2 -m ollama --livre --estilo analogico\n"
        ),
    )
    _arg_ajuda(p_ex)
    _arg_categoria(p_ex)
    _args_prompt(p_ex)

    # ── listar ─────────────────────────────────────────────────────────────────
    p_ls = _sub(sub, "listar", ["ls", "l"],
        "Lista categorias, prompts definitivos e rascunhos pendentes",
        "Mostra todos os prompts salvos e rascunhos de uma categoria ou de todas.\n"
        "Exibe também o número real de combinações disponíveis para cada categoria.",
        exemplos=(
            "  encena.py listar\n"
            "  encena.py listar -c canyon\n"
        ),
    )
    _arg_ajuda(p_ls)
    _arg_categoria(p_ls, obrigatorio=False)

    # ── promover ───────────────────────────────────────────────────────────────
    p_pv = _sub(sub, "promover", ["pv"],
        "Move rascunho para o JSON definitivo",
        "Move um prompt do arquivo de rascunhos para o JSON definitivo da categoria.\n"
        "Rascunhos são criados pelo comando 'experimentar'.\n"
        "Use 'todos' como nome para promover todos os rascunhos de uma vez.",
        exemplos=(
            "  encena.py promover canyon_livre -c canyon\n"
            "  encena.py promover todos -c canyon\n"
        ),
    )
    _arg_ajuda(p_pv)
    p_pv.add_argument("nome", metavar="NOME",
                      help="Nome do rascunho a promover, ou 'todos' para promover todos")
    _arg_categoria(p_pv)

    # ── remover ────────────────────────────────────────────────────────────────
    p_rm = _sub(sub, "remover", ["rm"],
        "Remove prompt do JSON definitivo",
        "Remove permanentemente um prompt do JSON definitivo da categoria.\n"
        "Use 'todos' como nome para remover todos (solicita confirmação).\n"
        "Para ver os nomes dos prompts: encena.py listar -c CATEGORIA",
        exemplos=(
            "  encena.py remover bryce_sunrise -c canyon\n"
            "  encena.py remover todos -c canyon\n"
        ),
    )
    _arg_ajuda(p_rm)
    p_rm.add_argument("nome", metavar="NOME",
                      help="Nome do prompt a remover, ou 'todos' para remover todos")
    _arg_categoria(p_rm)

    # ── estilos ────────────────────────────────────────────────────────────────
    p_es = _sub(sub, "estilos", ["es"],
        "Lista os estilos fotográficos disponíveis",
        "Exibe todos os estilos disponíveis com suas descrições e parâmetros técnicos.\n"
        "Estilos são usados com --estilo nos comandos 'prompts' e 'experimentar'.",
    )
    _arg_ajuda(p_es)

    # ── parse e dispatch ───────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.acao is None:
        parser.print_help()
        sys.exit(0)

    def validar_categorias(cats_str: str | None, todas: bool = False) -> list[str]:
        disponiveis = listar_categorias()
        if todas:
            return disponiveis
        if not cats_str:
            return []
        cats = [c.strip() for c in cats_str.split(",")]
        for c in cats:
            if c not in disponiveis:
                print(f"ERRO: categoria '{c}' não encontrada.")
                print(f"  Disponíveis: {disponiveis}")
                sys.exit(1)
        return cats

    if args.acao in ("estilos", "es"):
        print(f"\n  {'ESTILO':<16}  DESCRIÇÃO")
        print(f"  {'─' * 16}  {'─' * 50}")
        for chave, cfg in ESTILOS_FOTO.items():
            print(f"  {chave:<16}  {cfg['descricao']}")
            print(f"  {'':16}  abertura : {cfg['abertura']}")
            print(f"  {'':16}  captura  : {cfg['captura']}")
            print()
        return

    if args.acao in ("listar", "ls", "l"):
        cmd_listar(args.categoria)
        return

    if args.acao in ("promover", "pv"):
        cats = validar_categorias(args.categoria)
        cmd_promover(cats[0], args.nome)
        return

    if args.acao in ("remover", "rm"):
        cats = validar_categorias(args.categoria)
        cmd_remover(cats[0], args.nome)
        return

    if args.acao in ("imagens", "im"):
        cats = validar_categorias(args.categoria, getattr(args, "todas", False))
        if not cats:
            print("ERRO: imagens requer --categoria CAT ou --todas")
            sys.exit(1)
        print(f"\n  Gerando {args.quantidade} imagem(ns) por categoria")
        cmd_imagens(cats, args.quantidade, args.prompt_nome)
        return

    if args.acao in ("prompts", "pr"):
        cats = validar_categorias(args.categoria)
        print(f"\n  Gerando {args.quantidade} prompt(s) para '{cats[0]}'")
        print(f"  Configs : {CONFIGS_DIR}/{cats[0]}.json")
        cmd_prompts(
            categoria=cats[0], quantidade=args.quantidade,
            modo=args.modo, livre=args.livre,
            bioma=args.bioma, hora=args.hora, clima=args.clima,
            perspectiva=args.perspectiva, elemento=args.elemento,
            simular=args.simular, estilo=args.estilo,
        )
        return

    if args.acao in ("experimentar", "ex"):
        cats = validar_categorias(args.categoria)
        print(f"\n  Experimentando {args.quantidade} prompt(s) para '{cats[0]}'")
        print(f"  Configs : {CONFIGS_DIR}/{cats[0]}.json")
        cmd_experimentar(
            categoria=cats[0], quantidade=args.quantidade,
            modo=args.modo, livre=args.livre,
            bioma=args.bioma, hora=args.hora, clima=args.clima,
            perspectiva=args.perspectiva, elemento=args.elemento,
            estilo=args.estilo,
        )
        return


if __name__ == "__main__":
    main()
