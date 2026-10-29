<!-- MW-BRAND:BEGIN — gerado por IA/tools/mw-brand.sh · não editar à mão -->
<p align="center">
  <a href="https://github.com/visaodeempresa">
    <img src="https://mayconsoftware.github.io/assets/ve/LOGO_VISAO_DE_EMPRESA_HEIGHT-64px.png" alt="Visão de Empresa — MAYCON WILLIAN OLIVEIRA" height="64">
  </a>
  <br>
  <sub><b>Visão de Empresa</b> · projeto autoral mantido por Maycon Willian Oliveira</sub>
</p>
<!-- MW-BRAND:END -->

# MW Lúmina (`mw_lumina`)

Iluminação circadiana por ambiente para o Home Assistant — motor local determinístico, painel visual completo e funcionamento 100% offline.

> **Lúmina: a luz que se adapta a você.** A casa acorda com o Sol escorregando para o âmbar, trabalha no branco neutro da sua produtividade, emplaca o cinema na luz mínima e amolece ao seu descanso — sem depender de nuvem, sem internet, sem adivinhação.

---

## O que ela faz (Fase 1)

| Capacidade | Descrição |
| :--- | :--- |
| **Motor circadiano local** | Curva de Kelvin/brilho a partir da **elevação do Sol** calculada pelo HA (cartografia astronômica de baixo custo, sem API) — baseada em fotorreceptores de melanopsina (480 nm) |
| **Casa → Ambiente → Luz** | Configuração de toda a casa, por ambiente ou luz individual, com herança e sobreposição na cadeia `luz > ambiente > casa` |
| **Horário × dia da semana** | Blocos de agenda editáveis visualmente (a partir de "22:00 de sexta vai mais devagar"), incluindo blocos que **atravessam a meia-noite** |
| **Modulações ambientais** | Temperatura (calor → luz mais fresca; frio → mais aconchegante), umidade, coberturas de nuvens e condições do clima — tudo além do ciclo solar |
| **Clipes de segurança** | Teto/piso de Kelvin e brilho por luz (hardware limitado nunca é torturado) |
| **11 cenários predefinidos** | `Por do Sol`, `Amanhecer`, `Trabalho`, `Foco Profundo`, `Cinema`, `Descanso`, `Leitura`, `Jantar`, `Festa`, `Romântico`, `Madrugada` |
| **Cenas com duração** | A cena segura por X minutos; ao expirar, o circadiano **reassume sozinho** |
| **Modo manual inteligente** | O Lúmina detecta quando *você* mexeu na luz e deixa o ambiente em paz; o Auto volta com um clique |
| **Proteção noturna** | Janela de sono limita a casa a ≤ 2200K e ≤ 15% — vence cena, agenda e clima |
| **Painel visual completo** | Sidebar → **MW Lúmina**: curva solar ao vivo, deck de cenas, easy-mode por ambiente, matriz de luzes, agenda da casa |
| **Serviços para voz** | `mw_lumina.apply_scene/send pronto para a Letícia e automações` |
| **Offline-first** | Todos os cálculos são locais;.sem internet a casa continua seguindo o círculo do Sol |

### Fase 2 (em construção, já arquitetada)

O painel reserva o slot **"IA e Câmeras"**: snapshot da câmera → análise híbrida (IA local no Mac + nuvem como *fallback*) → ajustes de Kelvin/brilho dentro de limites de segurança. Os contratos de dados e a aba já existem — nenhum usuário da Fase 1 fica obsoleto.

---

## Instalação (via HACS)

1. **HACS → ⋮ → Repositório personalizado**
2. Cole: `visaodeempresa/mw-ha-lumina`
3. Categoria: **Integração** → **Adicionar**
4. Após baixar: **reinicie o Home Assistant**
5. **Configurações → Dispositivos e serviços → Adicionar integração → MW Lúmina**
6. O Lúmina descobre as áreas e luzes e abre o painel na sidebar.

> Sem HACS? Clone este repositório e copie `custom_components/mw_lumina/` para `/config/custom_components/`.

---

## Uso

### Painel
A sidebar ganha o ícone da lâmpada automática com o **MW Lúmina**:

- **Início** — a curva solar da sua casa em tempo real, deck de cenas da casa inteira e "Ambientes agora" com Kelvin/brilho de cada luz.
- **Ambientes** — adicione por área; por ambiente: luzes, blocos de horário (com dia da semana), clipes, botões de cena e o *test drive* de 60 s.
- **Luzes** — matriz geral, com clipes individuais para hardware especial (use quando uma lâmpada precisa de limites próprios).
- **Cenas** — as 11 predefinidas + suas cenas customizadas (nome, Kelvin ao vivo, brilho, descrição).
- **Sistema** — nome da casa, sensores de temperatura/umidade/clima, proteção noturna, agenda da casa, diagnóstico e export/import de configuração em JSON.

### Serviços

```yaml
# casa toda
action: mw_lumina.apply_scene
data:
  scene: cinema

# só um ambiente por 45 minutos
action: mw_lumina.apply_scene
data:
  scene: trabalho
  room: escritorio
  minutes: 45

# devolver o ambiente ao circadiano
action: mw_lumina.set_mode
data:
  room: escritorio
  mode: auto
```

Cada ambiente expõe `sensor.mw_lumina_*_alvo` (Kelvin atual + fonte e modificadores) e `select.mw_lumina_*_modo` (Auto/Manual) — perfeito para a Letícia e seus dashboards.

### Como a cadeia de decisão funciona

```
sua cena explícita (hold com expiração)
  ▼
bloco de agenda do ambiente/luz → tipo "scene" → tipo "fixed" → tipo "circadian"
  ▼
curva solar (elevação do Sol) × clima × temperatura × umidade
  ▼
clipes (luz ⊗ ambiente ⊗ casa)
  ▼
proteção noturna (se ativa)
```

### Arquitetura e estabilidade

- **Um único loop de 20 s** calcula e aplica — sem corrida de automações concorrentes.
- **Nunca liga luz apagada**; toca apenas nas lados que estão `on`, corrigindo Devonância percebível (tolerâncias de 30 K / 2%).
- Config em `Store` HA (`.storage/mw_lumina_config`), com validador de schema em toda escrita — mutação inválida é recusada, nunca aplicada pela metade.
- Qualquer exceção de dispositivo é absorvida e logada; o ciclo continua.
- Modo manual com *debounce* de 2 ciclos: o seu "mexe" não é pisado de volta no giro seguinte.

## Desenvolvimento

```bash
pip install -r requirements-test.txt
pytest -q          # suíte offline rápida (curvas, agenda, cenas, clipes)
ruff check .
```

CI cobre `ruff`, `pytest`, import real contra HA instalado, `hassfest`, validação HACS e coerência de manifest — vire os workflows para ver o que cada job checa.

## Licença

MIT — [LICENSE](LICENSE)
