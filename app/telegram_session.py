"""Сессия aiogram, которая умеет ходить через прокси хостинга.

Зачем: на бесплатном PythonAnywhere прямой выход в интернет закрыт, весь
трафик идёт через их прокси (переменные http_proxy/https_proxy). aiohttp
учитывает их по умолчанию, но на Windows он читает ещё и реестр, где VPN
прописывает свой прокси — а он Bot API как раз и режет.

Поэтому we передаём trust_env явно: на хостинге — True, на ПК — False.

В aiogram 3.20 у AiohttpSession нет параметра trust_env (kwargs уходят в
базовый класс и падают с TypeError), поэтому переопределяем create_session.
"""

from __future__ import annotations

from typing import Any

from aiogram import __version__
from aiogram.client.session.aiohttp import (
    SERVER_SOFTWARE,
    USER_AGENT,
    AiohttpSession,
)
from aiohttp import ClientSession


class ProxyAwareSession(AiohttpSession):
    """AiohttpSession с явным управлением системным прокси."""

    def __init__(self, *, trust_env: bool = False, **kwargs: Any) -> None:
        self._trust_env = trust_env
        super().__init__(**kwargs)

    async def create_session(self) -> ClientSession:  # type: ignore[override]
        if self._should_reset_connector:
            await self.close()

        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=self._connector_type(**self._connector_init),
                headers={
                    USER_AGENT: f"{SERVER_SOFTWARE} aiogram/{__version__}",
                },
                trust_env=self._trust_env,
            )
            self._should_reset_connector = False

        return self._session
