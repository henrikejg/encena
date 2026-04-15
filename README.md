# encena

Gerador de prompts e imagens fotorrealistas de paisagens naturais.

Combina um LLM local (Ollama) para criação de prompts com o ComfyUI para renderização via Stable Diffusion XL. O fluxo completo: gerar prompts → revisar em rascunhos → promover os bons → gerar imagens em alta resolução.

---

## Dependências

### Python
- Python 3.10+

### Ollama (opcional — para geração de prompts com IA)
- [ollama.com](https://ollama.com) — instale e baixe um modelo:
  ```bash
  ollama pull mistral:7b
  ```
- Sem Ollama, o script usa o modo combinatório (sorteia elementos de listas curadas).

### ComfyUI (para geração de imagens)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) rodando em `http://localhost:8188`
- Modelos necessários em `ComfyUI/models/`:

| Tipo | Arquivo |
|------|---------|
| Checkpoint | `checkpoints/DreamShaperXL_Lightning.safetensors` |
| LoRA | `loras/add-detail-xl.safetensors` |
| LoRA | `loras/LoRA-NaturePhotoreal-landscapes-SDXL-v1.safetensors` |
| Upscaler | `upscale_models/RealESRGAN_x4plus.pth` |

---

## Instalação

```bash
git clone https://github.com/<seu-usuario>/encena.git
cd encena
# Nenhuma dependência Python além da stdlib
```

---

## Uso

```
encena.py AÇÃO [opções]
```

Use `encena.py --ajuda` para a ajuda geral, ou `encena.py AÇÃO --ajuda` para ajuda detalhada de cada ação.

---

### Ações

#### `prompts` (`pr`) — Gera e salva prompts

Gera novos prompts via Ollama ou combinatório e salva no JSON da categoria.

```bash
# Gerar 5 prompts para canyon (modo auto: Ollama se disponível, senão combinatório)
encena.py prompts -c canyon -q 5

# Forçar modo Ollama com liberdade criativa total
encena.py prompts -c canyon -q 3 -m ollama --livre

# Usar estilo fotográfico específico
encena.py prompts -c aurora_boreal -q 3 --estilo noturno

# Visualizar sem salvar (dry-run)
encena.py prompts -c canyon -q 3 --simular

# Forçar elementos específicos
encena.py prompts -c canyon -q 2 --bioma 'zion narrow canyon' --hora sunrise
```

**Opções principais:**

| Flag | Descrição |
|------|-----------|
| `-c`, `--categoria` | Categoria alvo (ex: `canyon`, `aurora_boreal`) |
| `-q`, `--quantidade` | Quantidade de prompts (default: 3) |
| `-m`, `--modo` | `auto` \| `combinatorio` \| `ollama` (default: `auto`) |
| `--livre` | Ollama escolhe o cenário livremente, sem base combinatório |
| `-e`, `--estilo` | Estilo fotográfico (ver `encena.py estilos`) |
| `-s`, `--simular` | Exibe sem salvar |

---

#### `imagens` (`im`) — Gera imagens a partir dos prompts salvos

Lê os prompts do JSON e envia para o ComfyUI. Requer ComfyUI rodando.

```bash
# 3 imagens da categoria canyon
encena.py imagens -c canyon -q 3

# 1 imagem de todas as categorias
encena.py imagens --todas -q 1

# Forçar prompt específico
encena.py imagens -c canyon -q 5 --prompt-nome bryce_sunrise

# Múltiplas categorias
encena.py imagens -c "canyon,lavanda" -q 2
```

Saída em: `~/ComfyUI/output/landscapes/<categoria>/`

---

#### `experimentar` (`ex`) — Gera prompt + imagem sem comprometer o JSON

Ideal para testar novas ideias. Os prompts ficam em rascunhos para revisão posterior.

```bash
encena.py experimentar -c canyon -q 2 --livre
encena.py experimentar -c aurora_boreal -q 3 --estilo noturno
encena.py experimentar -c lavanda -q 2 -m ollama --livre --estilo analogico
```

Saída em: `~/ComfyUI/output/landscapes/<categoria>/experimentos/`

---

#### `listar` (`ls`) — Lista prompts e rascunhos

```bash
# Todas as categorias
encena.py listar

# Categoria específica (mostra combinações disponíveis)
encena.py listar -c canyon
```

---

#### `promover` (`pv`) — Move rascunho para o JSON definitivo

```bash
encena.py promover canyon_livre -c canyon
encena.py promover todos -c canyon
```

---

#### `remover` (`rm`) — Remove prompt do JSON definitivo

```bash
encena.py remover bryce_sunrise -c canyon
encena.py remover todos -c canyon   # pede confirmação
```

---

#### `estilos` (`es`) — Lista os estilos fotográficos

```bash
encena.py estilos
```

Estilos disponíveis:

| Estilo | Descrição |
|--------|-----------|
| `padrao` | DSLR versátil, tudo nítido |
| `ultrawide` | Grande angular — céu enorme, perspectiva dramática |
| `telefoto` | Sujeito isolado, fundo desfocado (bokeh) |
| `medioformato` | Detalhe extraordinário, dinâmica extrema |
| `noturno` | Abertura máxima, grain atmosférico de ISO alto |
| `longaexposicao` | Água e nuvens sedosas, 30s com tripé |
| `analogico` | Scan de filme — paleta orgânica, grão de película |
| `aereo` | Drone — perspectiva de cima, ampla profundidade de campo |

---

## Categorias incluídas

| Categoria | Biomas temáticos | Elementos temáticos |
|-----------|-----------------|---------------------|
| `canyon` | Arizona slot canyon, Grand Canyon, Bryce, Zion... | Sandstone walls, rock arches, light beams... |
| `aurora_boreal` | Iceland, Norway Tromsø, Alaska, Lapland... | Aurora curtains, frozen lake reflections... |
| `floresta_bambu` | Arashiyama, Sagano, Yunnan highlands... | Dense stalks, dappled light, mist between trunks... |
| `lago_alpino` | Swiss Alps, Dolomites, Patagonia, Rockies... | Mirror reflections, glacial water, wildflowers... |
| `lavanda` | Provence, Valensole, Brihuega, Hokkaido... | Endless rows, stone farmhouse, bee on bloom... |
| `praia_por_do_sol` | Caribbean, Hawaii, Maldives, Bali... | Golden reflection on sand, palm silhouettes... |

---

## Workflow recomendado

```bash
# 1. Experimentar sem comprometer nada
encena.py experimentar -c canyon -q 3 --livre

# 2. Ver o que foi gerado
encena.py listar -c canyon

# 3. Promover os prompts aprovados
encena.py promover todos -c canyon

# 4. Gerar mais imagens com os prompts que ficaram bons
encena.py imagens -c canyon -q 5
```

---

## Estrutura do projeto

```
encena/
├── encena.py          # Script principal
├── README.md
└── categorias/        # JSONs de configuração por categoria
    ├── canyon.json
    ├── aurora_boreal.json
    ├── floresta_bambu.json
    ├── lago_alpino.json
    ├── lavanda.json
    └── praia_por_do_sol.json
```

Cada `<categoria>.json` define parâmetros do ComfyUI (cfg, LoRA strengths, steps, sampler) e os prompts salvos.
