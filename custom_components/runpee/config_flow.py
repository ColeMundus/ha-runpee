"""Account-free player setup, options and recoverable legacy reconfiguration."""

import re
from typing import Any

import probatio as p
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN


def normalize_input(data: dict[str, Any]) -> dict[str, Any]:
    country = str(data.get("country", "US")).strip().upper()
    player = data.get("media_player")
    if (
        not re.fullmatch(r"[A-Z]{2}", country)
        or not isinstance(player, str)
        or not re.fullmatch(r"media_player\.[a-z0-9_]+", player)
    ):
        raise ValueError("Invalid configuration")
    return {"country": country, "media_player": player}


def timing_input(data: dict[str, Any]) -> dict[str, Any]:
    offset = data.get("timing_offset_seconds", 0)
    recommended = data.get("recommended_windows_only", False)
    if (
        isinstance(offset, bool)
        or not isinstance(offset, (int, float))
        or not -3600 <= offset <= 3600
        or int(offset) != offset
        or not isinstance(recommended, bool)
    ):
        raise ValueError("Invalid timing options")
    return {
        "timing_offset_seconds": int(offset),
        "recommended_windows_only": recommended,
    }


def schema(defaults: dict[str, Any], *, timing: bool = False) -> p.Schema:
    if timing:
        return p.Schema(
            {
                p.Optional(
                    "recommended_windows_only",
                    default=defaults.get("recommended_windows_only", False),
                ): selector.BooleanSelector(),
                p.Optional(
                    "timing_offset_seconds",
                    default=defaults.get("timing_offset_seconds", 0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-3600,
                        max=3600,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
    return p.Schema(
        {
            p.Required(
                "media_player",
                **(
                    {"default": defaults["media_player"]}
                    if defaults.get("media_player")
                    else {}
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            p.Required(
                "country", default=defaults.get("country", "US")
            ): selector.TextSelector(),
        }
    )


class RunPeeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return RunPeeOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = normalize_input(user_input)
            except ValueError:
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(data["media_player"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"RunPee {data['media_player'].split('.')[1]}", data=data
                )
        return self.async_show_form(
            step_id="user", data_schema=schema({}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = normalize_input(user_input)
            except ValueError:
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(data["media_player"])
                if entry.unique_id != data["media_player"]:
                    self._abort_if_unique_id_configured()
                changed = self.hass.config_entries.async_update_entry(
                    entry, unique_id=data["media_player"], data=data
                )
                # Loaded entries reload through their listener, failed legacy ones
                # have no listener yet. Avoid scheduling two overlapping reloads.
                if not changed or not entry.update_listeners:
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema(dict(entry.data)), errors=errors
        )


class RunPeeOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = timing_input(user_input)
            except ValueError, OverflowError:
                errors["base"] = "invalid_input"
            else:
                return self.async_create_entry(title="", data=data)
        return self.async_show_form(
            step_id="init",
            data_schema=schema(
                {**self.config_entry.data, **self.config_entry.options}, timing=True
            ),
            errors=errors,
        )
