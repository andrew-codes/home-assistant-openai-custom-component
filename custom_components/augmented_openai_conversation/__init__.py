"""The OpenAI Conversation integration."""
from __future__ import annotations

from functools import partial
import logging
from typing import Literal

import openai
from openai import error
import voluptuous as vol

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, MATCH_ALL
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    TemplateError,
)
from homeassistant.helpers import config_validation as cv, intent, selector, template
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import ulid

import json
from datetime import datetime, timedelta

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    CONF_LOCATION,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_PROMPT,
    DEFAULT_USER_REQUEST_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_LOCATION,
    DEFAULT_TOP_P,
    DOMAIN,
    CLARIFY_PROMPT,
)

_LOGGER = logging.getLogger(__name__)
SERVICE_GENERATE_IMAGE = "generate_image"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenAI Conversation."""

    async def render_image(call: ServiceCall) -> ServiceResponse:
        """Render an image with dall-e."""
        try:
            response = await openai.Image.acreate(
                api_key=hass.data[DOMAIN][call.data["config_entry"]],
                prompt=call.data["prompt"],
                n=1,
                size=f'{call.data["size"]}x{call.data["size"]}',
            )
        except error.OpenAIError as err:
            raise HomeAssistantError(f"Error generating image: {err}") from err

        return response["data"][0]

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_IMAGE,
        render_image,
        schema=vol.Schema(
            {
                vol.Required("config_entry"): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required("prompt"): cv.string,
                vol.Optional("size", default="512"): vol.In(("256", "512", "1024")),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenAI Conversation from a config entry."""
    try:
        await hass.async_add_executor_job(
            partial(
                openai.Engine.list,
                api_key=entry.data[CONF_API_KEY],
                request_timeout=10,
            )
        )
    except error.AuthenticationError as err:
        _LOGGER.error("Invalid API key: %s", err)
        return False
    except error.OpenAIError as err:
        raise ConfigEntryNotReady(err) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data[CONF_API_KEY]

    conversation.async_set_agent(hass, entry, OpenAIAgent(hass, entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload OpenAI."""
    hass.data[DOMAIN].pop(entry.entry_id)
    conversation.async_unset_agent(hass, entry)
    return True


class OpenAIAgent(conversation.AbstractConversationAgent):
    """OpenAI conversation agent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.history: dict[str, list[dict]] = {}

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence."""
        raw_user_prompt = self.entry.options.get(
            CONF_PROMPT, DEFAULT_USER_REQUEST_PROMPT)
        model = self.entry.options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        max_tokens = self.entry.options.get(
            CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        top_p = self.entry.options.get(CONF_TOP_P, DEFAULT_TOP_P)
        temperature = self.entry.options.get(
            CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        location = self.entry.options.get(
            CONF_LOCATION, DEFAULT_LOCATION)

        undefined_scripts = ""
        raw_prompt = DEFAULT_REQUEST_PROMPT.format(
            user_request_prompt=raw_user_prompt, location=location, future_time_stamp='%c'.format(datetime.now() + timedelta(hours=1)), undefined_scripts=undefined_scripts)

        if user_input.conversation_id in self.history:
            conversation_id = user_input.conversation_id
            messages = self.history[conversation_id]
        else:
            conversation_id = ulid.ulid()
            try:
                prompt = self._async_generate_prompt(raw_prompt)
                _LOGGER.info(prompt)
            except TemplateError as err:
                _LOGGER.error("Error rendering prompt: %s", err)
                intent_response = intent.IntentResponse(
                    language=user_input.language)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Sorry, I had a problem with my template: {err}",
                )
                return conversation.ConversationResult(
                    response=intent_response, conversation_id=conversation_id
                )
            messages = [{"role": "system", "content": prompt}]

        messages.append({"role": "user", "content": user_input.text})

        _LOGGER.debug("Prompt for %s: %s", model, messages)

        try:
            result = await openai.ChatCompletion.acreate(
                api_key=self.entry.data[CONF_API_KEY],
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                top_p=top_p,
                temperature=temperature,
                user=conversation_id,
            )
        except error.OpenAIError as err:
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I had a problem talking to OpenAI: {err}",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        _LOGGER.info("User Input", user_input.text)

        messages = await self.process_openai_result(
            conversation_id, user_input.text, result, messages, 0)

        self.history[conversation_id] = messages

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(messages[-1]["content"])
        return conversation.ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )

    async def process_openai_result(self, conversation_id: any, user_input_text: str, result: any, messages: [] = [], recursion_index: int = 0) -> any:
        _LOGGER.info("""Messages: %s
produced result: %s""", messages, result)

        if (recursion_index > 1):
            _LOGGER.info('Max recursion index reached. Returning messages.')
            return messages

        model = self.entry.options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        max_tokens = self.entry.options.get(
            CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        top_p = self.entry.options.get(CONF_TOP_P, DEFAULT_TOP_P)
        temperature = self.entry.options.get(
            CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        location = self.entry.options.get(
            CONF_LOCATION, DEFAULT_LOCATION)

        response = result["choices"][0]["message"]
        try:
            response_json = json.loads(response["content"])
            if response_json["action"] == "query":
                # for entity in response_json["entities"]:
                #     _LOGGER.info(entity)
                response["content"] = "Sorry, I don't know how to do that yet."
            elif response_json["action"] == "command":
                if response_json["scriptID"] != None:
                    [domain, entity_id] = response_json["scriptID"].split(".")
                    if self.hass.services.has_service(domain, entity_id) == True:
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                domain,
                                entity_id
                            )
                        )
                        response["content"] = response_json["comment"]
                    else:
                        messages.append(
                            {"role": "system", "content": CLARIFY_PROMPT.format(type="script", entity_id=response_json["scriptID"])})
                        messages.append(
                            {"role": "user", "content": user_input_text})
                        clarification_result = await openai.ChatCompletion.acreate(
                            api_key=self.entry.data[CONF_API_KEY],
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            top_p=top_p,
                            temperature=temperature,
                            user=conversation_id,
                        )
                        return await self.process_openai_result(
                            conversation_id, user_input_text, clarification_result, messages, recursion_index + 1)
                else:
                    response["content"] = "I'm sorry, I didn't understand that. Try rephrasing your request and try again."
            elif response_json["action"] == "set":
                response["content"] = response_json["comment"]
            elif response_json["action"] == "clarify":
                response["content"] = response_json["question"]
            elif response_json["action"] == "answer":
                response["content"] = response_json["answer"]

        except json.JSONDecodeError:
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I could not understand the response from OpenAI: {err}",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        messages.append(response)
        return messages

    def _async_generate_prompt(self, raw_prompt: str) -> str:
        """Generate a prompt for the user."""
        return template.Template(raw_prompt, self.hass).async_render(
            {
                "ha_name": self.hass.config.location_name,
            },
            parse_result=False,
        )
