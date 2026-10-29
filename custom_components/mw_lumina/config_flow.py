"""MW Lúmina — fluxo de configuração: apenas um passo de boas-vindas.

A configuração rica inteira acontece no painel visual (sidebar > MW Lúmina),
que grava no Store via WebSocket. Este flow só cria a entrada.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class LuminaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Boas-vindas + confirmação. Descoberta automática ocorre no setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(
            title="MW Lúmina",
            data={"name": user_input.get("name", "Minha Casa")},
        )


class LuminaOptionsFlow:
    """Sem options flow na Fase 1 — tudo pelo painel e pelo Store."""

    def __init__(self, config_entry) -> None:
        self.entry = config_entry
