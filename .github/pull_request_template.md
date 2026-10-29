Assunto: o que este PR muda

## O que muda
<!-- descrever em uma faixa: usuário vê o quê? -->

## Teste honesto
<!-- local: pytest; no HA: passo a passo que deu certo -->

## Checklist de qualidade da própria MW Lúmina
- [ ] `pytest -q` local verde
- [ ] `ruff check` verde
- [ ] sem segredo/`.env` em arquivo versionado
- [ ] manifest com order hassfest e versão sincronizada com o pyproject
- [ ] experiência do painel testada na tela (não só no código)
- [ ] README/CHANGELOG refletindo a mudança
