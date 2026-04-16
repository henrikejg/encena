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
import os
import random
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

# ─── Configuração ─────────────────────────────────────────────────────────────

CONFIGS_DIR  = Path(__file__).parent / "categorias"
OLLAMA_URL   = "http://localhost:11434"
COMFY_URL    = "http://localhost:8188"
CLIENT_ID    = str(uuid.uuid4())
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT", Path.home() / "ComfyUI" / "output"))
THUMB_MAX    = 500  # px — dimensão máxima do lado maior da thumbnail

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


def _tema_do_json(dados: dict) -> dict | None:
    """Extrai biomas/elementos do JSON da categoria, se existirem e forem válidos."""
    biomas    = dados.get("biomas") or []
    elementos = dados.get("elementos") or []
    if biomas and elementos:
        return {"biomas": biomas, "elementos": elementos}
    return None


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

# ─── Thumbnails ──────────────────────────────────────────────────────────────

def gerar_thumbnail(png_path: Path) -> bool:
    """Gera thumbnail JPEG em thumbs/ ao lado do PNG original.
    Não regera se o thumb já existir. Retorna True se bem-sucedido."""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print("  aviso: Pillow não instalado — instale com: pip install Pillow", flush=True)
        return False
    try:
        thumb_dir  = png_path.parent / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / (png_path.stem + ".jpg")
        if thumb_path.exists():
            return True
        with Image.open(png_path) as img:
            img.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
            img.save(thumb_path, "JPEG", quality=75, optimize=True)
        return True
    except Exception as e:
        print(f"  aviso: thumbnail falhou ({png_path.name}): {e}", flush=True)
        return False


def cmd_gerar_thumbs(categorias: list[str]) -> None:
    """Gera thumbnails para todas as imagens existentes nas categorias indicadas."""
    total = ok = ignoradas = 0
    for cat in categorias:
        cfg    = carregar_json(cat)
        subdir = cfg.get("output_subdir", f"landscapes/{cat}")
        base   = COMFY_OUTPUT / subdir
        dirs   = [base, base / "experimentos"]
        for d in dirs:
            if not d.exists():
                continue
            for f in sorted(d.glob("*.png")):
                thumb = f.parent / "thumbs" / (f.stem + ".jpg")
                if thumb.exists():
                    ignoradas += 1
                    continue
                total += 1
                if gerar_thumbnail(f):
                    ok += 1
                    print(f"  ✓  {f.relative_to(COMFY_OUTPUT)}", flush=True)
                else:
                    print(f"  ✗  {f.name}", flush=True)
    print(f"\n  {ok}/{total} gerado(s)  |  {ignoradas} já existia(m)")


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


def _tags_hint(tags: list[str] | None, modo: str = "refinar") -> str:
    """Gera a instrução de tags para o Ollama."""
    if not tags:
        return ""
    joined = ", ".join(tags)
    if modo == "refinar":
        return (
            f" The scene MUST incorporate these mandatory visual elements and themes: {joined}. "
            "Do NOT deviate from these themes — they define what this category is about."
        )
    # modo == "livre"
    return (
        f"\n\nMANDATORY VISUAL THEMES — your scene MUST include ALL of these elements: {joined}. "
        "These tags define the category. Ignoring them is not allowed."
    )


def ollama_refinar(base: str, modelo: str, categoria: str | None = None,
                   tags: list[str] | None = None) -> str:
    """Reescreve um prompt base com mais detalhes. Mantém o tema da categoria e as tags."""
    dica_tema = (
        f" The scene must belong to the '{categoria}' category "
        f"({_cat_hint(categoria)}) — "
        "keep all details thematically consistent with this theme."
    ) if categoria else ""
    dica_tags = _tags_hint(tags, "refinar")
    mensagem = (
        "Rewrite this nature photography prompt with more specific, evocative details "
        f"about light, texture, atmosphere and geography.{dica_tema}{dica_tags} "
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


def _cat_hint(categoria: str) -> str:
    """Adiciona nota de interpretação para nomes de categoria em português."""
    return (
        f"The category name '{categoria}' may be in Portuguese or another language — "
        "interpret it correctly into its English meaning before generating content. "
        "ALL output must be in English regardless of the category name's language."
    )


def ollama_normalizar_tags(tags: list[str], modelo: str) -> list[str]:
    """Traduz tags para inglês se necessário. Retorna a lista original em caso de falha."""
    mensagem = (
        "Translate the following photography keywords to English if they are not already. "
        "Keep the same meaning and level of specificity. "
        "Return ONLY a JSON array with the same number of items, in the same order.\n\n"
        f"Input: {json.dumps(tags, ensure_ascii=False)}"
    )
    try:
        resp = _ollama_post("/api/generate", {
            "model": modelo, "prompt": mensagem, "stream": False,
            "system": "You are a translator. Return ONLY a valid JSON array of strings, nothing else.",
        }, timeout=30)
        texto = resp.get("response", "").strip()
        match = re.search(r'\[.*\]', texto, re.DOTALL)
        if match:
            traduzidas = json.loads(match.group())
            if isinstance(traduzidas, list) and len(traduzidas) == len(tags):
                resultado = [str(t).strip() for t in traduzidas if str(t).strip()]
                print(f"  [ollama] tags normalizadas: {', '.join(resultado)}", flush=True)
                return resultado
    except Exception as e:
        print(f"  [ollama] erro ao normalizar tags: {e} — mantendo originais", flush=True)
    return tags


def ollama_gerar_tema(categoria: str, tags: list[str] | None,
                      modelo: str) -> dict | None:
    """Pede ao Ollama que gere biomas, elementos e tags para a categoria numa única chamada.
    Retorna {"biomas": [...], "elementos": [...], "tags": [...]} ou None em caso de falha."""
    tags_hint = f" Key visual themes already known: {', '.join(tags)}." if tags else ""
    mensagem = (
        f"Generate a complete visual profile for a '{categoria}' photography category.{tags_hint}\n\n"
        f"Note: {_cat_hint(categoria)}\n\n"
        "Return ONLY a JSON object with this exact structure — no markdown, no explanation:\n"
        '{"biomas": ["setting 1", ..., "setting 8"], '
        '"elementos": ["visual element 1", ..., "element 8"], '
        '"tags": ["keyword 1", ..., "keyword 8"]}\n\n'
        "Rules:\n"
        "- biomas: 8 DIVERSE settings or environments — this is critical:\n"
        "  * Cover a WIDE range: indoor AND outdoor, day AND night, action AND static\n"
        "  * Include both OBVIOUS settings (the first thing that comes to mind) AND "
        "SURPRISING/NON-OBVIOUS ones (interiors, unusual angles, unexpected contexts)\n"
        "  * Do NOT list 8 variations of the same setting type\n"
        "  * Example for 'sports cars': racing circuit, mountain hairpin road, "
        "showroom interior, cockpit interior view, underground parking, city boulevard at night, "
        "coastal highway, rainy tunnel\n"
        "- elementos: 8 specific visual subjects or focal points iconic to this category, "
        "also varied in scale and perspective (close-up details, wide establishing shots, etc.)\n"
        "- tags: 8 short keywords (1-3 words each) that define the visual identity of this category\n"
        "- All items in English, specific and visually evocative"
    )
    print("  [ollama] gerando tema e tags…", flush=True)
    try:
        resp = _ollama_post("/api/generate", {
            "model": modelo, "prompt": mensagem, "stream": False,
            "system": (
                "You are a geography and visual arts expert specialising in photography. "
                "You ONLY return valid JSON objects, nothing else — no prose, no markdown fences."
            ),
        }, timeout=60)
        texto = resp.get("response", "").strip()
        match = re.search(r'\{.*\}', texto, re.DOTALL)
        if not match:
            print(f"  [ollama] resposta sem JSON válido: {texto[:120]}", flush=True)
            return None
        data = json.loads(match.group())
        biomas    = [b.strip() for b in data.get("biomas",    []) if b.strip()]
        elementos = [e.strip() for e in data.get("elementos", []) if e.strip()]
        tags_geradas = [t.strip() for t in data.get("tags",   []) if t.strip()]
        if not biomas or not elementos:
            print("  [ollama] JSON incompleto — sem biomas ou elementos", flush=True)
            return None
        print(f"  [ollama] gerado: {len(biomas)} biomas, {len(elementos)} elementos, "
              f"{len(tags_geradas)} tags", flush=True)
        return {"biomas": biomas, "elementos": elementos, "tags": tags_geradas}
    except json.JSONDecodeError as e:
        print(f"  [ollama] JSON inválido: {e}", flush=True)
    except Exception as e:
        print(f"  [ollama] erro ao gerar tema: {e}", flush=True)
    return None


def ollama_livre(categoria: str, modelo: str, captura: str, abertura: str,
                 tags: list[str] | None = None,
                 bioma_forcado: str | None = None,
                 anti_repeticao: list[str] | None = None) -> str:
    """Ollama escolhe o cenário completo sem base fixo."""
    dica_tags = _tags_hint(tags, "livre")
    dica_bioma = (
        f" The scene MUST be set in/at this specific environment: '{bioma_forcado}'. "
        "Interpret it creatively but stay true to this setting."
    ) if bioma_forcado else ""
    dica_anti = (
        f"\n\nDo NOT repeat or closely resemble any of these already-used settings: "
        f"{'; '.join(anti_repeticao)}. Choose something clearly different."
    ) if anti_repeticao else ""
    mensagem = (
        f"Create an original Stable Diffusion XL prompt for a '{categoria}' photography scene. "
        f"{_cat_hint(categoria)}{dica_bioma} "
        "Be specific: name the exact setting, describe light quality, textures, atmosphere, "
        f"colors and composition.{dica_tags}{dica_anti} "
        "Return ONLY the prompt — no explanation, no quotes, no extra lines."
    )
    try:
        resp = _ollama_post("/api/generate", {
            "model": modelo, "prompt": mensagem, "stream": False,
            "system": (
                "You are an expert Stable Diffusion XL prompt engineer specialising in "
                "photorealistic photography. You have deep knowledge of visual subjects "
                "and always produce specific, vivid scenes with strong visual identity. "
                f"Always start responses with '{abertura} professional photography,' "
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
    import urllib.error
    body = json.dumps(dados).encode()
    req = urllib.request.Request(
        f"{COMFY_URL}/{endpoint}", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        print(f"ERRO ComfyUI {e.code}: {detalhe}", flush=True)
        raise


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
                          prefixo: str, seed: int,
                          orientacao: str = "vertical") -> dict:
    """
    Grafo ComfyUI construído dinamicamente.
    Os nós de LoraLoader só são incluídos quando há lora configurado na categoria.

      1   CheckpointLoader
      2   LoraLoader (lora_detail) — opcional
      3   LoraLoader (lora_nature) — opcional
      4   CLIPTextEncode positivo
      5   CLIPTextEncode negativo
      6   EmptyLatentImage
      7   KSampler
      8   VAEDecode
      9   UpscaleModelLoader
      10  ImageUpscaleWithModel
      11  SaveImage
    """
    ckpt_name   = cfg.get("checkpoint_name") or CHECKPOINT
    lora_d_name = cfg.get("lora_detail_name") or None
    lora_d_str  = float(cfg.get("lora_detail", 0.6))
    lora_n_name = cfg.get("lora_nature_name") or None
    lora_n_str  = float(cfg.get("lora_nature", 0.4))

    wf: dict = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt_name}},
    }

    last_model: list = ["1", 0]
    last_clip:  list = ["1", 1]

    if lora_d_name:
        wf["2"] = {"class_type": "LoraLoader",
                   "inputs": {"model": last_model, "clip": last_clip,
                              "lora_name": lora_d_name,
                              "strength_model": lora_d_str,
                              "strength_clip":  lora_d_str}}
        last_model, last_clip = ["2", 0], ["2", 1]

    if lora_n_name:
        wf["3"] = {"class_type": "LoraLoader",
                   "inputs": {"model": last_model, "clip": last_clip,
                              "lora_name": lora_n_name,
                              "strength_model": lora_n_str,
                              "strength_clip":  lora_n_str}}
        last_model, last_clip = ["3", 0], ["3", 1]

    w = cfg.get("height", 1344) if orientacao == "horizontal" else cfg.get("width",  768)
    h = cfg.get("width",   768) if orientacao == "horizontal" else cfg.get("height", 1344)

    wf.update({
        "4":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": positivo, "clip": last_clip}},
        "5":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": negativo,  "clip": last_clip}},
        "6":  {"class_type": "EmptyLatentImage",
               "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7":  {"class_type": "KSampler",
               "inputs": {"model": last_model, "positive": ["4", 0],
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
    })
    return wf


def comfy_enfileirar(workflow: dict) -> str:
    resultado = _comfy_post("prompt", {"prompt": workflow, "client_id": CLIENT_ID})
    return resultado["prompt_id"]


def comfy_aguardar(prompt_id: str, tag: str) -> list[Path]:
    """Aguarda conclusão do prompt. Retorna lista de Paths das imagens salvas (vazia = falha)."""
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
                imagens = [
                    img
                    for node in historico[prompt_id].get("outputs", {}).values()
                    for img in node.get("images", [])
                ]
                caminhos = [
                    COMFY_OUTPUT / img.get("subfolder", "") / img.get("filename", "")
                    for img in imagens
                    if img.get("filename")
                ]
                print(f"\r  {tag} | PRONTA em {elapsed:.0f}s{' ' * 10}", flush=True)
                for p in caminhos:
                    print(f"    -> output/{p.relative_to(COMFY_OUTPUT)}", flush=True)
                return caminhos
            elif status == "error":
                msgs = historico[prompt_id].get("status", {}).get("messages", [])
                print(f"\n  {tag} | ERRO: {msgs}", flush=True)
                return []

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
    tema_json: dict | None = None,
) -> dict:
    # Prioridade: JSON da categoria > TEMAS hardcoded > pools globais
    tema_code = TEMAS.get(categoria or "", {})
    biomas_pool    = (tema_json or {}).get("biomas")    or tema_code.get("biomas")    or BIOMAS
    elementos_pool = (tema_json or {}).get("elementos") or tema_code.get("elementos") or ELEMENTOS_FOCAIS
    return {
        "abertura":       abertura,
        "bioma":          bioma       or random.choice(biomas_pool),
        "hora":           hora        or random.choice(HORAS),
        "clima":          clima       or random.choice(CLIMAS),
        "perspectiva":    perspectiva or random.choice(PERSPECTIVAS),
        "elemento_focal": elemento    or random.choice(elementos_pool),
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
    tags: list[str] | None = None,
    tema_json: dict | None = None,
    prompts_anteriores: list[dict] | None = None,
) -> tuple[str, str]:
    """Gera um único (nome, texto) de prompt."""
    estilo_chave, abertura, captura = resolver_estilo(estilo)
    descricao_estilo = ESTILOS_FOTO[estilo_chave]["descricao"]

    if livre and modelo:
        # Força um bioma do pool temático para garantir diversidade
        bioma_forcado = bioma
        if not bioma_forcado and tema_json and tema_json.get("biomas"):
            bioma_forcado = random.choice(tema_json["biomas"])

        # Resume os últimos 5 prompts como contexto de anti-repetição
        anti_rep = None
        if prompts_anteriores:
            resumos = [p["text"][:80].replace("\n", " ") for p in prompts_anteriores[-5:]]
            anti_rep = resumos

        print(f"\n  [{i + 1}/{total}] ambiente: {bioma_forcado or 'livre'}")
        texto = ollama_livre(
            categoria, modelo, captura, abertura,
            tags=tags, bioma_forcado=bioma_forcado, anti_repeticao=anti_rep,
        )
        if not texto:  # fallback se Ollama falhar
            elementos = sortear_elementos(
                categoria, bioma, hora, clima, perspectiva, elemento,
                abertura, captura, tema_json=tema_json,
            )
            texto = TEMPLATE.format(**elementos)
        nome = make_name(categoria, "livre", existentes)
        print(f"  nome      : {nome}")
    else:
        elementos = sortear_elementos(
            categoria, bioma, hora, clima, perspectiva, elemento,
            abertura, captura, tema_json=tema_json,
        )
        base = TEMPLATE.format(**elementos)
        texto = ollama_refinar(base, modelo, categoria, tags=tags) if modelo else base
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
    tags: list[str] = dados.get("tags") or []
    tema_json = _tema_do_json(dados)

    if livre and modo == "combinatorio":
        print("  Aviso: --livre ignorado com --modo combinatorio (requer Ollama)")
    if tags:
        print(f"  tags da categoria : {', '.join(tags)}")
    if tema_json:
        print(f"  tema (JSON)       : {len(tema_json['biomas'])} biomas, "
              f"{len(tema_json['elementos'])} elementos")
    elif categoria not in TEMAS:
        print("  Aviso: categoria sem tema temático — modo combinatório usará pools globais")

    modelo = _resolver_modelo(modo, livre)
    novos: list[dict] = []
    # Acumula já-existentes + novos gerados na sessão para anti-repetição
    prompts_contexto: list[dict] = list(dados.get("prompts", []))

    for i in range(quantidade):
        nome, texto = _gerar_um_prompt(
            i, quantidade, categoria, modelo, livre,
            bioma, hora, clima, perspectiva, elemento, existentes, estilo,
            tags=tags or None, tema_json=tema_json,
            prompts_anteriores=prompts_contexto,
        )
        existentes.add(nome)
        novo = {"name": nome, "text": texto}
        novos.append(novo)
        prompts_contexto.append(novo)  # alimenta anti-repetição das próximas iterações

    if simular:
        print("\n  [simulação] nenhuma alteração salva.")
        return

    dados["prompts"].extend(novos)
    salvar_json(categoria, dados)
    print(f"\n  {len(novos)} prompt(s) adicionado(s) → {categoria}.json  "
          f"({len(dados['prompts'])} total)")


def cmd_imagens(
    categorias: list[str], quantidade: int, prompt_nome: str | None,
    orientacao: str = "vertical",
):
    jobs = [(cat, carregar_json(cat)) for cat in categorias]
    total = len(jobs) * quantidade

    fmt = "1344×768 (horizontal)" if orientacao == "horizontal" else "768×1344 (vertical)"
    print("=" * 70)
    print(f"  {len(jobs)} categoria(s) × {quantidade} imagem(ns) = {total} total")
    print(f"  Upscaler   : {UPSCALER}  |  Formato: {fmt}")
    print("=" * 70)
    for cat, cfg in jobs:
        n         = len(cfg.get("prompts", []))
        ckpt      = (cfg.get("checkpoint_name") or CHECKPOINT).replace(".safetensors", "")
        lora_d    = cfg.get("lora_detail_name") or ""
        lora_n    = cfg.get("lora_nature_name") or ""
        loras_str = "  +  ".join(l for l in [lora_d, lora_n] if l) or "sem lora"
        print(f"  • {cat:24s}  ckpt={ckpt}  loras={loras_str}  cfg={cfg['cfg']}  {n} prompts")
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
            wf = comfy_montar_workflow(cfg, ptexto, negativo, prefixo, seed, orientacao)
            pid = comfy_enfileirar(wf)
            fila.append((pid, tag))
            print(f"  Enfileirado {tag} | seed={seed} | id={pid[:8]}...")
            idx += 1
            time.sleep(0.3)

    print()
    resultados = [comfy_aguardar(pid, tag) for pid, tag in fila]
    sucessos   = sum(1 for r in resultados if r)
    print()
    print("=" * 70)
    print(f"  Concluído: {sucessos}/{total} imagens")
    print(f"  Local    : ~/ComfyUI/output/landscapes/")
    print("=" * 70)
    # Gera thumbnails para as imagens recém salvas
    n_thumbs = sum(
        1 for caminhos in resultados for p in caminhos
        if p.exists() and gerar_thumbnail(p)
    )
    if n_thumbs:
        print(f"  Thumbnails: {n_thumbs} gerado(s)")


def cmd_experimentar(
    categoria: str, quantidade: int, modo: str, livre: bool,
    bioma: str | None, hora: str | None, clima: str | None,
    perspectiva: str | None, elemento: str | None,
    estilo: str | None, orientacao: str = "vertical",
):
    dados = carregar_json(categoria)
    existentes: set[str] = (
        {p["name"] for p in dados.get("prompts", [])}
        | {r["name"] for r in carregar_rascunhos(categoria)}
    )
    tags: list[str] = dados.get("tags") or []
    tema_json = _tema_do_json(dados)

    if not comfy_disponivel():
        print(f"ERRO: ComfyUI não acessível em {COMFY_URL}")
        sys.exit(1)

    modelo = _resolver_modelo(modo, livre)
    negativo = dados.get("negative", NEGATIVE_DEFAULT)
    subdir = dados.get("output_subdir", f"landscapes/{categoria}")
    if tags:
        print(f"  tags da categoria : {', '.join(tags)}")
    if tema_json:
        print(f"  tema (JSON)       : {len(tema_json['biomas'])} biomas, "
              f"{len(tema_json['elementos'])} elementos")
    print(f"  ComfyUI: conectado — saída em output/{subdir}/experimentos/\n")

    novos: list[dict] = []
    prompts_contexto: list[dict] = list(dados.get("prompts", []))

    for i in range(quantidade):
        nome, texto = _gerar_um_prompt(
            i, quantidade, categoria, modelo, livre,
            bioma, hora, clima, perspectiva, elemento, existentes, estilo,
            tags=tags or None, tema_json=tema_json,
            prompts_anteriores=prompts_contexto,
        )
        existentes.add(nome)

        seed = random.randint(1, 2**32 - 1)
        prefixo = f"{subdir}/experimentos/{nome}_seed{seed}"
        wf = comfy_montar_workflow(dados, texto, negativo, prefixo, seed, orientacao)
        pid = comfy_enfileirar(wf)
        caminhos = comfy_aguardar(pid, f"[{i + 1}/{quantidade}] {nome}")
        for p in caminhos:
            if p.exists():
                gerar_thumbnail(p)

        rascunho = {"name": nome, "text": texto}
        adicionar_rascunho(categoria, rascunho)
        print(f"  Salvo em rascunhos: {nome}")
        novos.append(rascunho)
        prompts_contexto.append(rascunho)

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


def cmd_gerar_tema(categoria: str):
    """Gera biomas e elementos temáticos via Ollama e salva no JSON da categoria."""
    if not ollama_disponivel():
        print(f"ERRO: Ollama não acessível em {OLLAMA_URL}")
        sys.exit(1)
    modelo = ollama_escolher_modelo()
    if not modelo:
        print("ERRO: Ollama sem modelos instalados.")
        sys.exit(1)

    dados = carregar_json(categoria)
    tags  = dados.get("tags") or []
    print(f"\n  Gerando tema para '{categoria}' com {modelo}…")
    if tags:
        print(f"  Normalizando tags para inglês…")
        tags = ollama_normalizar_tags(tags, modelo)
        dados["tags"] = tags  # persiste a versão normalizada
        print(f"  tags      : {', '.join(tags)}")

    tema = ollama_gerar_tema(categoria, tags or None, modelo)
    if not tema:
        print("ERRO: Não foi possível gerar o tema. Tente novamente.")
        sys.exit(1)

    dados["biomas"]    = tema["biomas"]
    dados["elementos"] = tema["elementos"]
    # Atualiza tags apenas se a categoria não tiver nenhuma ainda
    if not dados.get("tags") and tema.get("tags"):
        dados["tags"] = tema["tags"]
        print(f"  tags      : {', '.join(tema['tags'])}")
    elif tema.get("tags"):
        print(f"  tags (mantidas) : {', '.join(dados.get('tags', []))}")
    salvar_json(categoria, dados)

    print(f"\n  Biomas ({len(tema['biomas'])}):")
    for b in tema["biomas"]:
        print(f"    • {b}")
    print(f"\n  Elementos ({len(tema['elementos'])}):")
    for e in tema["elementos"]:
        print(f"    • {e}")
    print(f"\n  Tema salvo em {categoria}.json")

    # Gera prompts iniciais se a categoria ainda não tiver nenhum
    if not dados.get("prompts"):
        print(f"\n  ── Gerando 10 prompts iniciais ──────────────────────────")
        cmd_prompts(
            categoria=categoria, quantidade=10, modo="ollama", livre=True,
            bioma=None, hora=None, clima=None,
            perspectiva=None, elemento=None,
            simular=False, estilo=None,
        )


def cmd_nova_categoria(nome: str, cfg: float, lora_nature: float, lora_detail: float,
                       steps: int, width: int, height: int,
                       tags: list[str] | None = None):
    slug = slugify(nome)
    path = CONFIGS_DIR / f"{slug}.json"
    if path.exists():
        print(f"ERRO: categoria '{slug}' já existe em {path}")
        sys.exit(1)
    # Tenta gerar tema temático via Ollama antes de salvar
    tema_gerado = None
    modelo = None
    if ollama_disponivel():
        modelo = ollama_escolher_modelo()
        if modelo:
            # Normaliza tags do usuário para inglês antes de usar como contexto
            if tags:
                print(f"  Normalizando tags para inglês…")
                tags = ollama_normalizar_tags(tags, modelo)
            print(f"  Ollama disponível ({modelo}) — gerando tema temático…")
            tema_gerado = ollama_gerar_tema(slug, tags or None, modelo)
        else:
            print("  Ollama sem modelos — tema será gerado manualmente depois.")
    else:
        print("  Ollama indisponível — tema será gerado quando disponível (use: gerar-tema).")

    # Se o usuário não forneceu tags, usa as geradas pelo Ollama
    tags_finais = tags or (tema_gerado.get("tags") if tema_gerado else None) or []

    dados = {
        "category": slug,
        "cfg": cfg,
        "lora_nature": lora_nature,
        "lora_detail": lora_detail,
        "steps": steps,
        "sampler": "dpmpp_2m_sde",
        "scheduler": "karras",
        "width": width,
        "height": height,
        "output_subdir": f"landscapes/{slug}",
        "negative": NEGATIVE_DEFAULT,
        "tags": tags_finais,
        "biomas": tema_gerado["biomas"]    if tema_gerado else [],
        "elementos": tema_gerado["elementos"] if tema_gerado else [],
        "prompts": [],
    }
    with open(path, "w") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\n  Categoria criada: {path}")
    print(f"  cfg={cfg}  lora_nature={lora_nature}  lora_detail={lora_detail}  steps={steps}")
    if tags_finais:
        origem = "(usuário)" if tags else "(geradas pelo Ollama)"
        print(f"  tags {origem} : {', '.join(tags_finais)}")
    if tema_gerado:
        print(f"  biomas    : {len(tema_gerado['biomas'])} locais gerados")
        print(f"  elementos : {len(tema_gerado['elementos'])} elementos gerados")
    else:
        print(f"  Aviso: sem tema — use: encena.py gerar-tema -c {slug}")

    # Gera prompts iniciais aproveitando o modelo já resolvido
    modelo_disponivel = tema_gerado is not None  # True se Ollama funcionou
    print(f"\n  ── Gerando 10 prompts iniciais ──────────────────────────")
    cmd_prompts(
        categoria=slug, quantidade=10,
        modo="ollama" if modelo_disponivel else "combinatorio",
        livre=modelo_disponivel,
        bioma=None, hora=None, clima=None,
        perspectiva=None, elemento=None,
        simular=False, estilo=None,
    )


def cmd_deletar_categoria(nome: str):
    path = CONFIGS_DIR / f"{nome}.json"
    if not path.exists():
        print(f"ERRO: categoria '{nome}' não encontrada.")
        print(f"  Disponíveis: {listar_categorias()}")
        sys.exit(1)
    rascunhos_path = CONFIGS_DIR / f"{nome}_rascunhos.json"
    dados = carregar_json(nome)
    n_prompts = len(dados.get("prompts", []))
    n_rasc = len(carregar_rascunhos(nome))
    print(f"  Atenção: deletar a categoria '{nome}' removerá permanentemente:")
    print(f"    • {path.name}  ({n_prompts} prompt(s))")
    if rascunhos_path.exists():
        print(f"    • {rascunhos_path.name}  ({n_rasc} rascunho(s))")
    print("  Digite 'sim' para confirmar: ", end="", flush=True)
    if input().strip().lower() != "sim":
        print("  Cancelado.")
        sys.exit(0)
    path.unlink()
    if rascunhos_path.exists():
        rascunhos_path.unlink()
        print(f"  Removido: {rascunhos_path.name}")
    print(f"  Removido: {path.name}")
    print(f"  Categoria '{nome}' deletada.")


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
                ("prompts",           "pr",  "Gera prompts e salva no JSON da categoria"),
                ("imagens",           "im",  "Gera imagens a partir dos prompts salvos"),
                ("experimentar",      "ex",  "Gera prompts + imagens sem salvar (guarda em rascunhos)"),
                ("listar",            "ls",  "Lista categorias, prompts e rascunhos"),
                ("promover",          "pv",  "Move rascunho para o JSON definitivo"),
                ("remover",           "rm",  "Remove prompt do JSON definitivo"),
                ("nova-categoria",    "nc",  "Cria uma nova categoria"),
                ("gerar-tema",        "gt",  "Gera tema temático para categoria via Ollama"),
                ("deletar-categoria", "dc",  "Remove uma categoria permanentemente"),
                ("estilos",           "es",  "Lista os estilos fotográficos disponíveis"),
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
            "  prompts           Gera prompts e salva no JSON da categoria\n"
            "  imagens           Gera imagens a partir dos prompts salvos\n"
            "  experimentar      Gera prompts + imagens sem salvar (guarda em rascunhos)\n"
            "  listar            Lista categorias, prompts definitivos e rascunhos\n"
            "  promover          Move rascunho para o JSON definitivo\n"
            "  remover           Remove prompt do JSON definitivo\n"
            "  nova-categoria    Cria uma nova categoria\n"
            "  gerar-tema        Gera tema temático para categoria via Ollama\n"
            "  deletar-categoria Remove uma categoria permanentemente\n"
            "  estilos           Lista os estilos fotográficos disponíveis\n"
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
    p_im.add_argument("--orientacao", "-o",
                      choices=["vertical", "horizontal"], default="vertical",
                      help="Orientação da imagem: vertical (768×1344, padrão) ou horizontal (1344×768)")

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
    p_ex.add_argument("--orientacao", "-o",
                      choices=["vertical", "horizontal"], default="vertical",
                      help="Orientação da imagem: vertical (768×1344, padrão) ou horizontal (1344×768)")

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

    # ── nova-categoria ─────────────────────────────────────────────────────────
    p_nc = _sub(sub, "nova-categoria", ["nc"],
        "Cria uma nova categoria com configurações padrão",
        "Cria o arquivo JSON da categoria no diretório 'categorias/'.\n"
        "As configurações podem ser ajustadas com os parâmetros opcionais.\n"
        "O nome é convertido para slug automaticamente (ex: 'Floresta Fria' → 'floresta_fria').",
        exemplos=(
            "  encena.py nova-categoria -n deserto\n"
            "  encena.py nova-categoria -n 'floresta_fria' --cfg 1.8 --lora-nature 0.4\n"
        ),
    )
    _arg_ajuda(p_nc)
    p_nc.add_argument("--nome", "-n", metavar="NOME", required=True,
                      help="Nome da nova categoria (ex: deserto, floresta_fria)")
    p_nc.add_argument("--cfg", type=float, default=1.8,
                      help="Valor CFG do KSampler (default: 1.8)")
    p_nc.add_argument("--lora-nature", type=float, default=0.4,
                      dest="lora_nature",
                      help="Força da LoRA de natureza (default: 0.4)")
    p_nc.add_argument("--lora-detail", type=float, default=0.6,
                      dest="lora_detail",
                      help="Força da LoRA de detalhes (default: 0.6)")
    p_nc.add_argument("--steps", type=int, default=8,
                      help="Passos do KSampler (default: 8)")
    p_nc.add_argument("--width", type=int, default=768,
                      help="Largura em pixels (default: 768)")
    p_nc.add_argument("--height", type=int, default=1344,
                      help="Altura em pixels (default: 1344)")
    p_nc.add_argument("--tags", "-t", metavar="TAGS",
                      help="Palavras-chave separadas por vírgula que direcionam o Ollama.\n"
                           "Ex: 'coral reef, bioluminescent fish, deep sea, underwater light'")

    # ── gerar-tema ─────────────────────────────────────────────────────────────
    p_gt = _sub(sub, "gerar-tema", ["gt"],
        "Gera (ou regenera) o tema temático de uma categoria via Ollama",
        "Usa o Ollama para criar listas de biomas e elementos visuais específicos\n"
        "para a categoria. Salva no JSON e passa a ser usado pelo modo combinatório.\n"
        "Use para categorias criadas sem Ollama disponível, ou para regenerar o tema.",
        exemplos=(
            "  encena.py gerar-tema -c fundo_do_mar\n"
            "  encena.py gerar-tema -c deserto\n"
        ),
    )
    _arg_ajuda(p_gt)
    _arg_categoria(p_gt)

    # ── deletar-categoria ──────────────────────────────────────────────────────
    p_dc = _sub(sub, "deletar-categoria", ["dc"],
        "Remove uma categoria e seus rascunhos permanentemente",
        "Apaga o JSON da categoria e o arquivo de rascunhos (se existir).\n"
        "Solicita confirmação antes de deletar.",
        exemplos=(
            "  encena.py deletar-categoria -c deserto\n"
        ),
    )
    _arg_ajuda(p_dc)
    _arg_categoria(p_dc)

    # ── gerar-thumbs ───────────────────────────────────────────────────────────
    p_th = _sub(sub, "gerar-thumbs", ["th"],
        "Gera thumbnails JPEG para imagens existentes sem thumbnail",
        "Processa todos os .png de uma categoria (ou de todas) e cria versões\n"
        "JPEG compactas em thumbs/ para uso no grid da galeria web.\n"
        "Imagens que já têm thumbnail são ignoradas automaticamente.\n"
        "Requer: pip install Pillow",
        exemplos=(
            "  encena.py gerar-thumbs -c canyon\n"
            "  encena.py gerar-thumbs --todas\n"
        ),
    )
    _arg_ajuda(p_th)
    _arg_categoria(p_th, obrigatorio=False)
    p_th.add_argument("--todas", action="store_true", default=False,
                      help="Processar todas as categorias")

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

    if args.acao in ("nova-categoria", "nc"):
        tags_parsed = (
            [t.strip() for t in args.tags.split(",") if t.strip()]
            if args.tags else None
        )
        cmd_nova_categoria(
            nome=args.nome,
            cfg=args.cfg,
            lora_nature=args.lora_nature,
            lora_detail=args.lora_detail,
            steps=args.steps,
            width=args.width,
            height=args.height,
            tags=tags_parsed,
        )
        return

    if args.acao in ("gerar-tema", "gt"):
        cats = validar_categorias(args.categoria)
        cmd_gerar_tema(cats[0])
        return

    if args.acao in ("deletar-categoria", "dc"):
        cats = validar_categorias(args.categoria)
        cmd_deletar_categoria(cats[0])
        return

    if args.acao in ("gerar-thumbs", "th"):
        cats = validar_categorias(args.categoria, getattr(args, "todas", False))
        if not cats:
            cats = listar_categorias()
        print(f"\n  Gerando thumbnails para: {', '.join(cats)}\n")
        cmd_gerar_thumbs(cats)
        return

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
        cmd_imagens(cats, args.quantidade, args.prompt_nome,
                    orientacao=getattr(args, "orientacao", "vertical"))
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
            orientacao=getattr(args, "orientacao", "vertical"),
        )
        return


if __name__ == "__main__":
    main()
