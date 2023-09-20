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
from homeassistant.helpers.area_registry import async_get
from homeassistant.helpers import config_validation as cv, intent, selector, template
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import ulid

import json
from datetime import datetime, timedelta

from .config import (
    CONF_CHAT_MODEL,
    CONF_COMMAND_PROMPT,
    CONF_HELP_PROMPT,
    CONF_MAX_TOKENS,
    CONF_QUERY_PROMPT,
    CONF_SET_PROMPT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DOMAIN,
)
from .ClarificationException import (
    ClarificationException, IntentClarificationException)

_LOGGER = logging.getLogger(__name__)
SERVICE_GENERATE_IMAGE = "generate_image"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenAI Conversation."""
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
        try:
            if user_input.conversation_id in self.history:
                conversation_id = user_input.conversation_id
                messages = self.history[conversation_id]
            else:
                conversation_id = ulid.ulid()
                self.intention = None

            if self.intention == None:
                intent_prompt = self.get_prompt('intent_detection')
                messages = [{"role": "system", "content": intent_prompt}]
                discover_intention_messages = messages + \
                    [{"role": "user", "content": user_input.text}]

                [intent_data, new_message] = await self.async_send_openai_messages("intent_detection", discover_intention_messages)
                self.intention = intent_data

                match self.intention:
                    case "set":
                        prompt = self.populate_prompt(CONF_SET_PROMPT)
                        messages.append({"role": "system", "content": prompt})

                    case "command":
                        prompt = self.populate_prompt(CONF_COMMAND_PROMPT)
                        messages.append({"role": "system", "content": prompt})

                    case "query":
                        prompt = self.populate_prompt(CONF_QUERY_PROMPT)
                        messages.append({"role": "system", "content": prompt})

                    case "help":
                        prompt = self.populate_prompt(CONF_HELP_PROMPT)
                        messages.append({"role": "system", "content": prompt})

                    case "unknown":
                        raise IntentClarificationException(
                            "Can you rephrase your request and try again?")
                    case _:
                        raise IntentClarificationException(
                            "Can you rephrase your request and try again?")

            messages.append(
                {"role": "user", "content": user_input.text})

            [content, new_message] = await self.async_send_openai_messages(conversation_id, messages)

            try:
                match self.intention:
                    case "set":
                        request_data = json.loads(content)

                        if request_data["entities"] == None:
                            raise ClarificationException(
                                "I couldn't find those devices. Can you specify different devices and ask again?")
                        elif request_data["set_value"] == None:
                            raise ClarificationException(
                                "I didn't understand what to set the devices to. Can you rephrase your request and ask again?")

                        new_message["content"] = request_data["comment"]

                    case "command":
                        request_data = json.loads(content)

                        if request_data["area"] == None:
                            raise ClarificationException(
                                "What room is that in?")
                        elif request_data["script_id"] == None:
                            raise ClarificationException(
                                "I'm not familiar with how to do that. Can you specify something else and ask again?")
                        elif self.hass.states.get(request_data["script_id"]) == None:
                            raise ClarificationException(
                                "I'm not able to complete your request in that room. Can you specify a different room and ask again?")

                        new_message["content"] = request_data["comment"]

            except json.JSONDecodeError as err:
                new_message["content"] = content

        except error.OpenAIError as err:
            _LOGGER.error("Network error rendering prompt: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except json.JSONDecodeError as err:
            _LOGGER.error("Error parsing JSON: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except TemplateError as err:
            _LOGGER.error(
                "Error rendering Home Assistant template: %s", err)
            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except IntentClarificationException as err:
            _LOGGER.debug("Need for intention clarification: %s", err)
            self.intention = None

            message = + "I'm sorry. " + str(err)
            new_message["content"] = message

            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                message,
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except ClarificationException as err:
            _LOGGER.debug("Need for clarification: %s", err)

            new_message["content"] = str(err)

            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                message,
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        except Exception as err:
            _LOGGER.error("Uncaught exception: %s", err)

            intent_response = intent.IntentResponse(
                language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Sorry, I'm having trouble completing your request.",
            )
            return conversation.ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        self.history[conversation_id] = messages

        intent_response = intent.IntentResponse(
            language=user_input.language)
        intent_response.async_set_speech(new_message["content"])

        return conversation.ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )

    async def async_send_openai_messages(self, conversation_id: any, messages: [] = []) -> any:
        model = self.entry.options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
        max_tokens = self.entry.options.get(
            CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        top_p = self.entry.options.get(CONF_TOP_P, DEFAULT_TOP_P)
        temperature = self.entry.options.get(
            CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        _LOGGER.debug("Prompt for %s: %s", model, messages)

        result = await openai.ChatCompletion.acreate(
            api_key=self.entry.data[CONF_API_KEY],
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            top_p=top_p,
            temperature=temperature,
            user=conversation_id,
        )
        _LOGGER.info("Result for %s: %s", model, result)

        message = result["choices"][0]["message"]

        return [message["content"], message]

    def _async_generate_prompt(self, raw_prompt: str) -> str:
        """Generate a prompt for the user."""
        return template.Template(raw_prompt, self.hass).async_render(
            {
                "ha_name": self.hass.config.location_name,
            },
            parse_result=False,
        )

    def populate_prompt(prompt_name: str) -> str:
        prompt = self.entry.options.get(prompt_name, "")

        return self._async_generate_prompt(prompt)

    def get_prompt(prompt_name: str) -> str:
        prompt = pkgutil.get_data(__name__, "prompts/{file_name}.md.j2".format(
            file_name=prompt_name)).decode("utf-8")

        return self._async_generate_prompt(prompt)
