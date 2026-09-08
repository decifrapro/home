"""Leitura do conteúdo público de links citados na conversa.

Só páginas públicas, só HTTP e HTTPS, sem tentar burlar login ou paywall.
A URL original é sempre preservada na timeline, mesmo quando a leitura falha.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse, urlunparse

import httpx

from app.models.schemas import LinkItem, ProcessingStatus
from app.processors.base import LinkProcessorBase, ProcessingContext, ProcessingOutcome

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
MAX_CONTENT_CHARS = 20_000
STRIP_TAGS = ("script", "style", "noscript", "nav", "footer", "aside", "header", "form", "svg")
USER_AGENT = "DecifraPro/2.0 (+leitor de links de conversa; respeita robots do servidor)"


class BlockedURL(ValueError):
    """URL recusada por segurança (SSRF, esquema proibido, destino interno)."""


def normalize_url(raw: str) -> str:
    candidate = raw.strip()
    if candidate.lower().startswith("www."):
        candidate = "https://" + candidate
    return candidate


def assert_public_url(url: str) -> tuple[str, list[str]]:
    """Valida esquema e destino. Devolve (host, ips) ou levanta BlockedURL."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(f"esquema não permitido: {parsed.scheme or 'ausente'}")
    host = parsed.hostname
    if not host:
        raise BlockedURL("endereço sem host")
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".onion"):
        raise BlockedURL("destino interno ou anônimo bloqueado")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BlockedURL(f"não foi possível resolver o endereço: {exc}") from exc

    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise BlockedURL(f"endereço de rede interna bloqueado ({address})")
        addresses.append(address)
    return host, addresses


def _clean(text: str) -> str:
    return " ".join(text.split())


def extract_readable(html: str) -> tuple[str, str, str]:
    """(título, descrição, conteúdo legível) a partir do HTML."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    for tag in STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    title = ""
    for selector, attribute in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
        ("title", None),
    ):
        node = tree.css_first(selector)
        if node is not None:
            title = _clean(node.attributes.get(attribute, "") if attribute else node.text())
            if title:
                break

    description = ""
    for selector in ('meta[property="og:description"]', 'meta[name="description"]'):
        node = tree.css_first(selector)
        if node is not None:
            description = _clean(node.attributes.get("content", "") or "")
            if description:
                break

    body_node = tree.css_first("article") or tree.css_first("main") or tree.body
    content = _clean(body_node.text(separator=" ")) if body_node is not None else ""
    return title, description, content[:MAX_CONTENT_CHARS]


class LinkProcessor(LinkProcessorBase):
    async def process(self, link: LinkItem, context: ProcessingContext) -> ProcessingOutcome:
        settings = context.settings
        url = normalize_url(link.url)

        try:
            assert_public_url(url)
        except BlockedURL as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Link não lido: {exc}.",
                category="link",
                metadata={"blocked": True},
            )

        limit_bytes = settings.link_max_download_mb * 1024 * 1024
        try:
            status_code, final_url, content_type, body = await _fetch(
                url, settings.link_timeout_seconds, limit_bytes
            )
        except BlockedURL as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Link não lido: {exc}.",
                category="link",
                metadata={"blocked": True},
            )
        except httpx.TimeoutException:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error="Link não lido: o servidor não respondeu no tempo limite.",
                category="link",
            )
        except httpx.HTTPError as exc:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Link não lido: {exc}.",
                category="link",
            )

        if status_code >= 400:
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                error=f"Link não lido: o servidor respondeu {status_code}.",
                category="link",
                metadata={"http_status": status_code, "final_url": final_url},
            )

        if "html" not in content_type and not content_type.startswith("text/"):
            return ProcessingOutcome(
                status=ProcessingStatus.DONE,
                text=f"[conteúdo não textual: {content_type or 'tipo desconhecido'}]",
                metadata={"content_type": content_type, "final_url": final_url},
                category="link",
            )

        title, description, content = extract_readable(body)

        if len(content) < 200 and settings.enable_playwright:
            rendered = await _render_with_browser(url, settings.link_timeout_seconds)
            if rendered:
                title2, description2, content2 = extract_readable(rendered)
                title = title or title2
                description = description or description2
                if len(content2) > len(content):
                    content = content2

        return ProcessingOutcome(
            status=ProcessingStatus.DONE,
            text=content,
            metadata={
                "title": title,
                "description": description,
                "content_type": content_type,
                "final_url": final_url,
                "http_status": status_code,
            },
            category="link",
        )


async def _fetch(url: str, timeout: int, limit_bytes: int) -> tuple[int, str, str, str]:
    """Busca a página seguindo redirects manualmente, revalidando cada destino."""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_public_url(current)
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise BlockedURL("redirecionamento sem destino")
                    current = str(httpx.URL(current).join(location))
                    continue

                content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                collected = bytearray()
                async for chunk in response.aiter_bytes():
                    collected.extend(chunk)
                    if len(collected) > limit_bytes:
                        break
                text = bytes(collected).decode(response.encoding or "utf-8", errors="replace")
                return response.status_code, _sanitize(current), content_type, text
    raise BlockedURL("excesso de redirecionamentos")


def _sanitize(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


async def _render_with_browser(url: str, timeout: int) -> str | None:
    """Fallback opcional para páginas que só montam o conteúdo via JavaScript."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("Playwright não instalado; fallback de navegador desativado")
        return None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(args=["--no-sandbox"])
            try:
                page = await browser.new_page(user_agent=USER_AGENT)
                await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                return await page.content()
            finally:
                await browser.close()
    except Exception as exc:  # pragma: no cover - depende do navegador instalado
        logger.warning("fallback de navegador falhou: %s", exc)
        return None
