"""MW Lúmina — registro de cenários predefinidos (Fase 1).

Cenas são "intenções de luz": valores-alvo explícitos que sobrepõem o
circadiano e o agendador, mantendo os clipes de segurança (clipes maison).
A fase 2 (IA/câmera) pode ajustar deltas sobre estas cenas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Transição default em segundos ao aplicar cena
DEFAULT_TRANSITION = 3.0


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    name: str
    icon: str
    kelvin: int
    brightness: int  # percentual
    description: str
    transition: float = DEFAULT_TRANSITION
    effect: str | None = None  # ex. "colorloop" (se suportado pela luz)
    emotion: str = ""  # palavras-chave para o painel / voz (Letícia, fase 2)


SCENES: dict[str, Scene] = {
    "por_do_sol": Scene(
        "por_do_sol", "Pôr do Sol", "mdi:weather-sunset", 2000, 35,
        "Âmbar densa e envolvente, como o fim de tarde entrando pela janela.",
        emotion="acolhedor calmo",
    ),
    "amanhecer": Scene(
        "amanhecer", "Amanhecer", "mdi:weather-sunset-up", 3300, 55,
        "Primeira luz da manhã, convidativa para a rotina de início de dia.",
        emotion="animado suave",
    ),
    "trabalho": Scene(
        "trabalho", "Trabalho", "mdi:briefcase", 5000, 85,
        "Branco neutro alerta para concentração e leitura de telas.",
        emotion="foco produtivo",
    ),
    "foco_profundo": Scene(
        "foco_profundo", "Foco Profundo", "mdi:brain", 5600, 95,
        "Máxima clareza fria para tarefas críticas de curta duração.",
        emotion="alerta intenso",
    ),
    "cinema": Scene(
        "cinema", "Cinema", "mdi:projector", 1900, 8,
        "Resquício de luz âmbar apenas para orientar o ambiente.",
        emotion="imersivo discreto",
    ),
    "descanso": Scene(
        "descanso", "Descanso", "mdi:sofa", 2200, 22,
        "Luz morna baixa, de relaxar corpo e mente no fim do dia.",
        emotion="morno sereno",
    ),
    "leitura": Scene(
        "leitura", "Leitura", "mdi:book-open-variant", 4000, 76,
        "Luz direta confortável para páginas e detalhes.",
        emotion="claro confortável",
    ),
    "jantar": Scene(
        "jantar", "Jantar", "mdi:silverware-fork-knife", 2700, 55,
        "Luz de mesa morna e generosa, festiva por dentro.",
        emotion="convidativo quente",
    ),
    "festa": Scene(
        "festa", "Festa", "mdi:party-popper", 5000, 95,
        "Luz plena com colorloop nas luzes compatíveis (quando marcado).",
        effect="colorloop",
        emotion="festa vibrante",
    ),
    "romantico": Scene(
        "romantico", "Romântico", "mdi:heart", 1800, 15,
        "Luz mínima dourada para silêncios e conversas.",
        emotion="íntimo dourado",
    ),
    "madrugada": Scene(
        "madrugada", "Madrugada", "mdi:weather-night", 1700, 4,
        "Só um fio de luz para circular sem despertar a casa.",
        emotion="noite mínima",
    ),
}

SCENE_ORDER = list(SCENES)


def scene_to_dict(scene: Scene) -> dict:
    return asdict(scene)


def resolve_scene(scene_id: str, custom_scenes: dict[str, dict]) -> Scene | None:
    """Busca a cena predefinida, com fallback para uma cena customizada."""
    scene = SCENES.get(scene_id)
    if scene:
        return scene
    data = custom_scenes.get(scene_id)
    if not data:
        return None
    try:
        return Scene(
            id=scene_id,
            name=data.get("name", scene_id),
            icon=data.get("icon", "mdi:lightbulb-on"),
            kelvin=int(data.get("kelvin", 2700)),
            brightness=int(data.get("brightness", 50)),
            description=data.get("description", ""),
            transition=float(data.get("transition", DEFAULT_TRANSITION)),
            effect=data.get("effect"),
            emotion=data.get("emotion", ""),
        )
    except (TypeError, ValueError):
        return None
