# encena v0.3.0

Gerador de prompts e imagens fotorrealistas via Ollama + ComfyUI (Stable Diffusion XL).

Combina um LLM local (Ollama/Mistral) para criação de prompts temáticos com o ComfyUI para renderização em alta resolução. A partir da **v0.2.0**, inclui uma **interface web** completa para gerenciar categorias, gerar prompts e imagens, revisar rascunhos e configurar parâmetros — sem precisar usar a linha de comando.

---

## Interface Web

```bash
cd web
node server.js
# Acesse http://localhost:3131
# Acesso pela rede local: http://<IP-DA-MÁQUINA>:3131
```

Requer Node.js 18+. Nenhuma dependência npm — usa apenas a stdlib do Node.

### Painéis disponíveis

| Painel | Função |
|--------|--------|
| **Gerar Imagens** | Envia prompts salvos para o ComfyUI renderizar |
| **Experimentar** | Gera prompt + imagem sem comprometer o JSON definitivo |
| **Prompts** | Gera e gerencia prompts salvos por categoria |
| **Categorias** | CRUD completo de categorias com config, prompts, rascunhos |
| **Galeria** | Visualiza, avalia e exclui imagens geradas por categoria |

### Destaques da interface

- **Terminal em tempo real** — saídas do Python aparecem via SSE (Server-Sent Events) enquanto o processo executa
- **Nova categoria com IA** — ao criar, o Ollama gera automaticamente tags temáticas, biomas, elementos e 10 prompts iniciais
- **Mass delete** — seleção múltipla de prompts e rascunhos com exclusão em lote
- **Indicadores de status** — pills no header mostram se ComfyUI e Ollama estão online
- **Tema combinatório por categoria** — cada categoria tem seus próprios pools de biomas e elementos (gerados via Ollama), garantindo diversidade temática nos prompts
- **Checkpoint e LoRAs por categoria** — cada categoria pode ter seu próprio checkpoint e até 2 LoRAs configurados via combobox; os modelos disponíveis são carregados diretamente do ComfyUI
- **Orientações separadas na geração** — ao gerar imagens, é possível definir quantidades independentes para orientação vertical e horizontal no mesmo pedido
- **Sistema de votos em prompts** — cada prompt tem contadores de thumbs up/down; deletar uma imagem da galeria registra automaticamente um voto negativo no prompt que a gerou; os prompts são sempre exibidos ordenados por pontuação (up − down)
- **Galeria com delete** — imagens podem ser excluídas diretamente da galeria (apaga o PNG em alta resolução e a thumbnail)

---

## CLI (encena.py)

O script Python continua funcional de forma independente.

```
encena.py AÇÃO [opções]
```

Use `encena.py --ajuda` para a ajuda geral, ou `encena.py AÇÃO --ajuda` para ajuda detalhada de cada ação.

---

## Dependências

### Python
- Python 3.10+  (sem dependências externas além da stdlib)

### Node.js (interface web)
- Node.js 18+  (sem dependências npm)

### Ollama (opcional — geração de prompts com IA)
- [ollama.com](https://ollama.com) — instale e baixe um modelo:
  ```bash
  ollama pull mistral:7b
  ```
- Sem Ollama, o sistema usa o modo combinatório (sorteia elementos de listas curadas).

### ComfyUI (geração de imagens)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) rodando em `http://localhost:8188`
- Modelos mínimos em `ComfyUI/models/`:

| Tipo | Arquivo |
|------|---------|
| Checkpoint | `checkpoints/DreamShaperXL_Lightning.safetensors` |
| LoRA | `loras/add-detail-xl.safetensors` |
| LoRA | `loras/LoRA-NaturePhotoreal-landscapes-SDXL-v1.safetensors` |
| Upscaler | `upscale_models/RealESRGAN_x4plus.pth` |

> Cada categoria pode referenciar seus próprios checkpoint e LoRAs. Todos os modelos instalados no ComfyUI aparecem automaticamente nos comboboxes da interface.

---

## Instalação

```bash
git clone https://github.com/henrikejg/encena.git
cd encena

# Interface web
cd web && node server.js

# Ou via CLI diretamente
python3 encena.py --ajuda
```

---

## Ações CLI

#### `prompts` (`pr`) — Gera e salva prompts

```bash
encena.py prompts -c canyon -q 5
encena.py prompts -c canyon -q 3 -m ollama --livre
encena.py prompts -c aurora_boreal -q 3 --estilo noturno
encena.py prompts -c canyon -q 3 --simular          # dry-run
encena.py prompts -c canyon -q 2 --bioma 'zion narrow canyon' --hora sunrise
```

| Flag | Descrição |
|------|-----------|
| `-c` | Categoria alvo |
| `-q` | Quantidade de prompts (default: 3) |
| `-m` | `auto` \| `combinatorio` \| `ollama` |
| `--livre` | Ollama escolhe cenário livremente |
| `-e` | Estilo fotográfico |
| `--simular` | Exibe sem salvar |

---

#### `imagens` (`im`) — Gera imagens a partir dos prompts salvos

```bash
encena.py imagens -c canyon -q 3
encena.py imagens --todas -q 1
encena.py imagens -c canyon -q 5 --prompt-nome bryce_sunrise
encena.py imagens -c "canyon,lavanda" -q 2
```

Saída em: `~/ComfyUI/output/<output_subdir>/`

---

#### `experimentar` (`ex`) — Gera prompt + imagem sem comprometer o JSON

```bash
encena.py experimentar -c canyon -q 2 --livre
encena.py experimentar -c aurora_boreal -q 3 --estilo noturno
```

Saída em: `~/ComfyUI/output/<output_subdir>/experimentos/`

---

#### `nova-categoria` (`nc`) — Cria nova categoria

```bash
encena.py nova-categoria -n 'floresta_fria'
encena.py nova-categoria -n 'deserto' --cfg 2.0 --steps 10 --tags 'dunes, heat haze, camels'
```

Com Ollama disponível, gera automaticamente: tags temáticas, biomas, elementos e 10 prompts iniciais.

---

#### `gerar-tema` — Regenera tema combinatório de uma categoria existente

```bash
encena.py gerar-tema -c canyon
```

---

#### `listar` (`ls`), `promover` (`pv`), `remover` (`rm`)

```bash
encena.py listar
encena.py listar -c canyon
encena.py promover canyon_livre -c canyon
encena.py promover todos -c canyon
encena.py remover bryce_sunrise -c canyon
```

---

#### `estilos` (`es`) — Lista os estilos fotográficos disponíveis

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

| Categoria | Tags temáticas |
|-----------|----------------|
| `canyon` | slot canyon, sandstone, desert light, rock formations |
| `aurora_boreal` | aurora, northern lights, polar sky, ice reflections |
| `floresta_bambu` | bamboo forest, japanese garden, misty grove, soft light |
| `lago_alpino` | alpine lake, mountain reflection, glacial water, wildflowers |
| `lavanda` | lavender field, provence, purple rows, golden hour |
| `praia_por_do_sol` | beach sunset, tropical coast, golden ocean, palm silhouettes |
| `cafe_da_manha` | breakfast table, morning light, coffee, warm interior |
| `carros_esportivos` | sports car, racing circuit, motion blur, urban streets |
| `fundo_do_mar` | coral reef, bioluminescent fish, deep sea, underwater light |
| `sala_de_estar` | living room, interior design, cozy lighting, architecture |
| `avioes_de_guerra` | fighter jet, military aircraft, dogfight, afterburner, clouds |
| `grandes_felinos` | big cat, wildlife photography, savanna, stalking, golden light |
| `material_escolar` | school supplies, stationery, flat lay, colorful, desk |
| `trens` | locomotive, railway, steam engine, countryside, motion |

Cada categoria tem seu próprio tema combinatório (biomas + elementos) gerado via Ollama, garantindo diversidade nos prompts.

---

## Sistema de votos em prompts

Cada prompt armazena contadores `up` e `down` diretamente no JSON da categoria. A pontuação para ordenação é `up − down`.

- **Thumbs up** — disponível na galeria ao lado de cada imagem
- **Thumbs down automático** — ao deletar uma imagem da galeria, o prompt que a gerou recebe um voto negativo automaticamente
- **Ordenação** — em todos os painéis que exibem prompts (Prompts, Gerar Imagens, Galeria), os prompts são listados do maior para o menor score

---

## Como funciona a geração de prompts

O encena usa duas estratégias complementares:

**Modo combinatório** — sorteia biomas e elementos do pool temático da categoria (ou global) e monta um prompt estruturado. Rápido, sem dependências, 100% determinístico.

**Modo Ollama** — envia o contexto da categoria (nome, tags, bioma sorteado, histórico recente) para o Mistral gerar um prompt criativo em inglês. Mecanismos de diversidade:
- Rotação forçada de biomas a cada geração
- Anti-repetição: últimos 5 prompts passados como contexto
- Tags da categoria injetadas no system prompt

**Modo livre** — Ollama escolhe o cenário sem base combinatório fixo. Mais variação, menos previsibilidade.

---

## Estrutura do projeto

```
encena/
├── encena.py              # CLI principal (Python, zero dependências externas)
├── README.md
├── web/
│   ├── server.js          # Servidor web local (Node.js, zero dependências npm)
│   ├── index.html         # Interface single-page
│   └── favicon.svg        # Ícone do projeto
└── categorias/            # JSONs de configuração e prompts por categoria
    ├── canyon.json
    ├── aurora_boreal.json
    ├── floresta_bambu.json
    ├── lago_alpino.json
    ├── lavanda.json
    ├── praia_por_do_sol.json
    ├── cafe_da_manha.json
    ├── carros_esportivos.json
    ├── fundo_do_mar.json
    ├── sala_de_estar.json
    ├── avioes_de_guerra.json
    ├── grandes_felinos.json
    ├── material_escolar.json
    └── trens.json
```

Cada `<categoria>.json` contém: checkpoint e LoRAs específicos, parâmetros do KSampler (cfg, steps, sampler, scheduler), tags temáticas, pools de biomas e elementos, prompts salvos com contadores de votos.

---

## Workflow recomendado

```bash
# Via interface web (recomendado)
cd web && node server.js
# Acesse http://localhost:3131

# Via CLI
encena.py experimentar -c canyon -q 3 --livre   # testa sem comprometer
encena.py listar -c canyon                       # revisa o que foi gerado
encena.py promover todos -c canyon               # promove os aprovados
encena.py imagens -c canyon -q 5                 # gera imagens em alta res
```
