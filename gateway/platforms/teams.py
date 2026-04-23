"""
Microsoft Teams 플랫폼 어댑터.

Bot Framework Webhook 방식으로 Teams 메시지를 수신하고,
Bot Framework REST API(serviceUrl)를 통해 응답을 전송합니다.

환경변수:
  TEAMS_BOT_APP_ID       — Azure Bot App ID
  TEAMS_BOT_APP_PASSWORD — Azure Bot App Password (Client Secret)
  TEAMS_WEBHOOK_PORT     — Webhook 리스닝 포트 (기본 8765)
  TEAMS_WEBHOOK_PATH     — Webhook 경로 (기본 /teams/webhook)
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

# Teams 메시지 최대 길이 (Adaptive Card 텍스트 기준)
MAX_MESSAGE_LENGTH = 28000


# ---------------------------------------------------------------------------
# OAuth2 토큰 캐시 — serviceUrl에 응답할 때 Bearer 토큰 필요
# ---------------------------------------------------------------------------

@dataclass
class _TokenCache:
    """Bot Framework OAuth 토큰 캐시."""
    access_token: str = ""
    expires_at: float = 0.0  # time.monotonic() 기준

    def is_valid(self) -> bool:
        # 만료 30초 전에 갱신
        return bool(self.access_token) and time.monotonic() < self.expires_at - 30


# ---------------------------------------------------------------------------
# Teams 어댑터
# ---------------------------------------------------------------------------

class TeamsAdapter(BasePlatformAdapter):
    """
    Microsoft Teams Bot Framework 어댑터.

    Teams → Hermes: POST /teams/webhook (Activity JSON)
    Hermes → Teams: serviceUrl + /v3/conversations/{conv_id}/activities

    인증 흐름:
      1. Bot Framework가 webhook으로 Activity를 POST 전송 (JWT 서명 포함)
      2. 응답 시 Microsoft OAuth2로 Bearer 토큰 발급 후 serviceUrl에 POST
    """

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.TEAMS)

        self._app_id = os.getenv("TEAMS_BOT_APP_ID", config.token or "")
        self._app_password = os.getenv("TEAMS_BOT_APP_PASSWORD", config.api_key or "")
        self._port = int(os.getenv("TEAMS_WEBHOOK_PORT", "8765"))
        self._path = os.getenv("TEAMS_WEBHOOK_PATH", "/teams/webhook")

        # AIDE API 경유 발신 (아이다 계정 공유) — AIDE_AGENT_KEY 설정 시 활성화
        self._aide_url = os.getenv("AIDE_API_URL", "http://localhost:8000").rstrip("/")
        self._aide_key = os.getenv("AIDE_AGENT_KEY", "")

        # OAuth 토큰 캐시
        self._token_cache = _TokenCache()
        self._token_lock = asyncio.Lock()

        # 실행 중인 webhook 서버 task
        self._server_task: Optional[asyncio.Task] = None
        self._server = None  # asyncio Server 인스턴스

    # ------------------------------------------------------------------
    # 추상 메서드 구현
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Webhook HTTP 서버를 시작해 Teams 메시지 수신을 시작합니다."""
        if not self._app_id:
            logger.error("[Teams] TEAMS_BOT_APP_ID가 설정되지 않았습니다.")
            return False
        if not self._app_password:
            logger.warning("[Teams] TEAMS_BOT_APP_PASSWORD 미설정 — JWT 검증 비활성화")

        try:
            self._server_task = asyncio.create_task(self._run_webhook_server())
            self._running = True
            logger.info(
                "[Teams] Webhook 서버 시작: port=%d path=%s",
                self._port, self._path,
            )
            return True
        except Exception as e:
            logger.error("[Teams] 서버 시작 실패: %s", e, exc_info=True)
            return False

    async def disconnect(self) -> None:
        """Webhook 서버를 종료합니다."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("[Teams] 연결 해제")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """
        Teams 채널/대화에 메시지를 전송합니다.

        AIDE_AGENT_KEY 설정 시: AIDE /agent/notify/teams API 경유 (아이다 계정으로 발신)
        미설정 시: Bot Framework serviceUrl 직접 발신 (봇 계정)

        Args:
            chat_id: "serviceUrl|||conversationId" 형식
            content: 전송할 텍스트 (Markdown 가능)
            reply_to: 미사용 (Teams는 thread 답장 구조 다름)
            metadata: 추가 옵션 (activity_id, channel 등)
        """
        metadata = metadata or {}

        # AIDE API 경유 발신 — 아이다 계정으로 "by 에르메스" 서명과 함께 전송
        if self._aide_key:
            return await self._send_via_aide(chat_id, content, metadata)

        # fallback: Bot Framework 직접 발신 (AIDE_AGENT_KEY 미설정 시)
        service_url, conversation_id = self._parse_chat_id(chat_id)
        if not service_url or not conversation_id:
            return SendResult(success=False, error=f"잘못된 chat_id 형식: {chat_id}")

        try:
            chunks = self.truncate_message(content, MAX_MESSAGE_LENGTH)
            last_result = None
            for chunk in chunks:
                last_result = await self._post_activity(
                    service_url=service_url,
                    conversation_id=conversation_id,
                    text=chunk,
                    activity_id=metadata.get("activity_id"),
                )
            return last_result or SendResult(success=False, error="전송된 청크 없음")
        except Exception as e:
            logger.error("[Teams] 메시지 전송 실패: %s", e, exc_info=True)
            return SendResult(success=False, error=str(e))

    async def _send_via_aide(
        self,
        chat_id: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> SendResult:
        """AIDE /agent/notify/teams API 경유로 아이다 계정 발신.

        X-Agent-Name: hermes 헤더로 AIDE에서 "by 에르메스" 서명을 붙여 발송한다.
        """
        import httpx

        _, conversation_id = self._parse_chat_id(chat_id)
        channel = metadata.get("channel", "server")

        payload: Dict[str, Any] = {
            "message": content[:1000],
            "channel": channel,
        }
        if conversation_id:
            payload["chat_id"] = conversation_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self._aide_url}/agent/notify/teams",
                    headers={
                        "X-Agent-Key": self._aide_key,
                        "X-Agent-Name": "hermes",
                        "Content-Type": "application/json",
                        # 무한 루프 방지: AIDE가 Hermes로 재위임하지 않게
                        "X-Forwarded-From": "hermes",
                    },
                    json=payload,
                )
            if resp.status_code == 200:
                logger.info("[Teams] AIDE 경유 발신 성공 chat_id=%s", conversation_id or channel)
                return SendResult(success=True)
            logger.warning("[Teams] AIDE 경유 발신 실패 status=%d body=%s", resp.status_code, resp.text[:200])
            return SendResult(success=False, error=f"AIDE API {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.error("[Teams] AIDE API 호출 실패: %s", e)
            return SendResult(success=False, error=str(e))

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """채널/대화 정보를 반환합니다."""
        _, conversation_id = self._parse_chat_id(chat_id)
        return {
            "name": conversation_id or chat_id,
            "type": "channel",
        }

    # ------------------------------------------------------------------
    # Webhook 서버 (순수 asyncio HTTP, 외부 의존성 없음)
    # ------------------------------------------------------------------

    async def _run_webhook_server(self) -> None:
        """asyncio 기반 최소 HTTP 서버로 Teams webhook을 수신합니다."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            host="0.0.0.0",
            port=self._port,
        )
        async with self._server:
            await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """단일 TCP 연결을 처리합니다 (HTTP/1.1 최소 파싱)."""
        try:
            # 요청 라인 파싱
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode("utf-8", errors="replace").strip().split()
            if len(parts) < 2:
                return
            method, path = parts[0], parts[1]

            # 헤더 파싱
            headers: Dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if ":" in decoded:
                    k, _, v = decoded.partition(":")
                    headers[k.strip().lower()] = v.strip()

            # 바디 읽기
            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # 라우팅
            if method == "POST" and path == self._path:
                status, response_body = await self._handle_teams_webhook(body, headers)
            elif path in ("/health", "/healthz"):
                status, response_body = 200, b'{"status":"ok"}'
            else:
                status, response_body = 404, b'{"error":"not found"}'

            # HTTP 응답 전송
            http_response = (
                f"HTTP/1.1 {status} OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode() + response_body
            writer.write(http_response)
            await writer.drain()

        except Exception as e:
            logger.warning("[Teams] 연결 처리 중 오류: %s", e)
        finally:
            writer.close()

    async def _handle_teams_webhook(
        self, body: bytes, headers: Dict[str, str]
    ) -> tuple:
        """
        Teams Bot Framework Activity를 파싱하고 처리를 시작합니다.

        TODO: JWT 서명 검증 추가
              Authorization: Bearer <token> 헤더를 확인하고
              https://login.botframework.com/v1/.well-known/openidconfiguration
              에서 공개키를 가져와 검증할 수 있습니다.
        """
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning("[Teams] JSON 파싱 실패: %s", e)
            return 400, b'{"error":"invalid json"}'

        activity_type = payload.get("type", "")

        # message 타입만 처리 (invoke, conversationUpdate, typing 등은 무시)
        if activity_type != "message":
            logger.debug("[Teams] activity 타입 무시: %s", activity_type)
            return 200, b'{"status":"ignored"}'

        # 비동기로 메시지 처리 (webhook에 즉시 200 응답)
        asyncio.create_task(self._process_incoming_activity(payload))
        return 200, b'{"status":"ok"}'

    # ------------------------------------------------------------------
    # 메시지 파싱 및 처리
    # ------------------------------------------------------------------

    async def _process_incoming_activity(self, payload: Dict[str, Any]) -> None:
        """Teams Activity를 MessageEvent로 변환해 handle_message를 호출합니다."""
        try:
            # 텍스트 추출 및 @mention 태그 정리
            raw_text = payload.get("text", "") or ""
            text = self._strip_at_mention(raw_text).strip()

            if not text:
                logger.debug("[Teams] 빈 메시지 무시")
                return

            # 발신자 정보
            from_info = payload.get("from", {}) or {}
            user_id = from_info.get("id", "")
            user_name = from_info.get("name", "")

            # 대화/채널 정보
            conversation = payload.get("conversation", {}) or {}
            conversation_id = conversation.get("id", "")
            is_group = conversation.get("isGroup", False)

            channel_data = payload.get("channelData", {}) or {}
            channel = channel_data.get("channel", {}) or {}
            team = channel_data.get("team", {}) or {}
            team_id = team.get("id", "")
            team_name = team.get("name", "")

            # serviceUrl — 응답 전송에 필수
            service_url = payload.get("serviceUrl", "").rstrip("/")

            # chat_id: "serviceUrl|||conversationId" 형식으로 인코딩
            chat_id = self._build_chat_id(service_url, conversation_id)

            # 채팅 타입 결정
            chat_type = "channel" if (is_group or team_id) else "dm"
            chat_name = team_name or conversation_id

            # 메시지 ID (activity id)
            message_id = payload.get("id", "")

            # SessionSource 구성
            source = self.build_source(
                chat_id=chat_id,
                chat_name=chat_name,
                chat_type=chat_type,
                user_id=user_id,
                user_name=user_name,
                thread_id=None,  # Teams 스레드 지원은 추후 확장
            )

            msg_event = MessageEvent(
                text=text,
                message_type=MessageType.TEXT,
                source=source,
                raw_message=payload,
                message_id=message_id,
            )

            logger.info(
                "[Teams] 메시지 수신 — user=%s chat_type=%s text=%.60s",
                user_name or user_id, chat_type, text,
            )

            await self.handle_message(msg_event)

        except Exception as e:
            logger.error("[Teams] 메시지 처리 오류: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Teams API 전송
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """
        Microsoft OAuth2로 Bot Framework Bearer 토큰을 발급합니다.
        캐시된 토큰이 유효하면 재사용합니다.
        """
        async with self._token_lock:
            if self._token_cache.is_valid():
                return self._token_cache.access_token

            if not self._app_id or not self._app_password:
                logger.warning("[Teams] 자격증명 미설정 — 인증 없이 전송 시도")
                return ""

            import httpx
            token_url = (
                "https://login.microsoftonline.com/botframework.com"
                "/oauth2/v2.0/token"
            )
            data = {
                "grant_type": "client_credentials",
                "client_id": self._app_id,
                "client_secret": self._app_password,
                "scope": "https://api.botframework.com/.default",
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(token_url, data=data)
                    resp.raise_for_status()
                    token_data = resp.json()
                    access_token = token_data["access_token"]
                    expires_in = int(token_data.get("expires_in", 3600))
                    self._token_cache.access_token = access_token
                    self._token_cache.expires_at = time.monotonic() + expires_in
                    logger.debug(
                        "[Teams] OAuth 토큰 발급 완료 (expires_in=%ds)", expires_in
                    )
                    return access_token
            except Exception as e:
                logger.error("[Teams] 토큰 발급 실패: %s", e, exc_info=True)
                return ""

    async def _post_activity(
        self,
        service_url: str,
        conversation_id: str,
        text: str,
        activity_id: Optional[str] = None,
    ) -> SendResult:
        """
        Bot Framework REST API로 Teams에 메시지를 전송합니다.

        endpoint: POST {serviceUrl}/v3/conversations/{conversationId}/activities
        """
        import httpx

        token = await self._get_access_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # activity_id가 있으면 특정 메시지에 reply
        if activity_id:
            endpoint = (
                f"{service_url}/v3/conversations/{conversation_id}"
                f"/activities/{activity_id}"
            )
        else:
            endpoint = (
                f"{service_url}/v3/conversations/{conversation_id}/activities"
            )

        body = {
            "type": "message",
            "text": text,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(endpoint, json=body, headers=headers)
                resp.raise_for_status()
                resp_data = resp.json()
                sent_id = resp_data.get("id", "")
                logger.debug("[Teams] 메시지 전송 완료: id=%s", sent_id)
                return SendResult(
                    success=True, message_id=sent_id, raw_response=resp_data
                )
        except Exception as e:
            logger.error(
                "[Teams] 전송 실패 (endpoint=%s): %s", endpoint, e, exc_info=True
            )
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_at_mention(text: str) -> str:
        """
        Teams @mention 태그를 제거합니다.

        예: "<at>봇이름</at> 안녕하세요" → "안녕하세요"
        """
        cleaned = re.sub(r"<at>[^<]*</at>", "", text)
        # 기본 HTML 엔티티 정리
        cleaned = (
            cleaned.replace("&amp;", "&")
                   .replace("&lt;", "<")
                   .replace("&gt;", ">")
                   .replace("&nbsp;", " ")
        )
        return cleaned.strip()

    @staticmethod
    def _build_chat_id(service_url: str, conversation_id: str) -> str:
        """serviceUrl과 conversationId를 chat_id 문자열로 인코딩합니다."""
        return f"{service_url}|||{conversation_id}"

    @staticmethod
    def _parse_chat_id(chat_id: str) -> tuple:
        """
        chat_id에서 serviceUrl과 conversationId를 파싱합니다.

        Returns:
            (service_url, conversation_id) — 파싱 실패 시 ("", chat_id)
        """
        if "|||" in chat_id:
            parts = chat_id.split("|||", 1)
            return parts[0], parts[1]
        # 구분자 없으면 conversationId만으로 간주
        return "", chat_id
