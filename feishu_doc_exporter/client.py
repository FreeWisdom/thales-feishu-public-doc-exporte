from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


JsonObject = Dict[str, Any]


class FeishuAPIError(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


@dataclass(frozen=True)
class DocumentRef:
    url: str
    token: str
    url_type: str
    export_type: str


def parse_document_ref(url_or_token: str, export_type: Optional[str] = None) -> DocumentRef:
    value = url_or_token.strip()
    if not value:
        raise ValueError("empty document URL/token")

    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme:
        guessed = export_type or "docx"
        return DocumentRef(url=value, token=value.strip("/"), url_type=guessed, export_type=guessed)

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"could not find document token in URL: {value}")

    url_type = parts[-2]
    token = parts[-1]
    if url_type == "docx":
        guessed = "docx"
    elif url_type in {"docs", "doc"}:
        guessed = "doc"
    else:
        guessed = export_type or url_type

    return DocumentRef(url=value, token=token, url_type=url_type, export_type=export_type or guessed)


class FeishuClient:
    def __init__(
        self,
        *,
        base_url: str = "https://open.feishu.cn",
        access_token: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout

    @property
    def access_token(self) -> str:
        if self._access_token:
            return self._access_token
        if not self.app_id or not self.app_secret:
            raise FeishuAPIError(
                "missing credentials: set FEISHU_ACCESS_TOKEN, or FEISHU_APP_ID and FEISHU_APP_SECRET"
            )
        payload = self._request_json(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            body={"app_id": self.app_id, "app_secret": self.app_secret},
            auth=False,
        )
        token = payload.get("tenant_access_token")
        if not token:
            raise FeishuAPIError("tenant_access_token not found in auth response", payload=payload)
        self._access_token = token
        return token

    def get_document_meta(self, document_id: str) -> JsonObject:
        return self._api_json("GET", f"/open-apis/docx/v1/documents/{quote_path(document_id)}")

    def get_document_raw_content(self, document_id: str) -> JsonObject:
        return self._api_json("GET", f"/open-apis/docx/v1/documents/{quote_path(document_id)}/raw_content")

    def list_document_blocks(self, document_id: str, *, page_size: int = 500) -> JsonObject:
        all_items = []
        pages = []
        page_token: Optional[str] = None

        while True:
            query: JsonObject = {"document_revision_id": -1, "page_size": page_size}
            if page_token:
                query["page_token"] = page_token
            payload = self._api_json(
                "GET",
                f"/open-apis/docx/v1/documents/{quote_path(document_id)}/blocks",
                query=query,
            )
            pages.append(payload)
            data = payload.get("data") or {}
            items = data.get("items") or data.get("blocks") or []
            if isinstance(items, list):
                all_items.extend(items)

            has_more = bool(data.get("has_more"))
            page_token = data.get("page_token") or data.get("next_page_token")
            if not has_more or not page_token:
                break

        return {"items": all_items, "pages": pages, "count": len(all_items)}

    def create_export_task(self, *, token: str, export_type: str, file_extension: str) -> JsonObject:
        return self._api_json(
            "POST",
            "/open-apis/drive/v1/export_tasks",
            body={"token": token, "type": export_type, "file_extension": file_extension},
        )

    def get_export_task(self, *, ticket: str, token: str) -> JsonObject:
        return self._api_json(
            "GET",
            f"/open-apis/drive/v1/export_tasks/{quote_path(ticket)}",
            query={"token": token},
        )

    def wait_for_export(
        self,
        *,
        ticket: str,
        token: str,
        timeout_seconds: int = 120,
        poll_interval: float = 2.0,
    ) -> JsonObject:
        deadline = time.time() + timeout_seconds
        last_payload: JsonObject = {}
        while time.time() < deadline:
            payload = self.get_export_task(ticket=ticket, token=token)
            last_payload = payload
            result = ((payload.get("data") or {}).get("result") or {})
            status = result.get("job_status")
            if status == 0 and result.get("file_token"):
                return payload
            if status in {2, 3}:
                raise FeishuAPIError("export task failed", payload=payload)
            time.sleep(poll_interval)

        raise FeishuAPIError("export task timed out", payload=last_payload)

    def download_export_file(self, *, file_token: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        url = self._url(f"/open-apis/drive/v1/export_tasks/file/{quote_path(file_token)}/download")
        request = urllib.request.Request(url, method="GET", headers=self._headers(auth=True))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                data = response.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise FeishuAPIError(f"network error: {exc}") from exc

        if "json" in content_type.lower():
            try:
                payload = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                payload = data.decode("utf-8", errors="replace")
            if isinstance(payload, dict) and payload.get("code", 0) != 0:
                raise FeishuAPIError(f"download failed: {payload.get('msg', 'unknown error')}", payload=payload)

        output_path.write_bytes(data)
        return output_path

    def _api_json(
        self,
        method: str,
        path: str,
        *,
        query: Optional[JsonObject] = None,
        body: Optional[JsonObject] = None,
    ) -> JsonObject:
        payload = self._request_json(method, path, query=query, body=body, auth=True)
        if payload.get("code", 0) != 0:
            raise FeishuAPIError(f"Feishu API error {payload.get('code')}: {payload.get('msg')}", payload=payload)
        return payload

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: Optional[JsonObject] = None,
        body: Optional[JsonObject] = None,
        auth: bool,
    ) -> JsonObject:
        data = None
        headers = self._headers(auth=auth)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = urllib.request.Request(self._url(path, query=query), data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise FeishuAPIError(f"network error: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FeishuAPIError("response is not JSON", payload=raw) from exc

    def _headers(self, *, auth: bool) -> Dict[str, str]:
        headers = {"User-Agent": "feishu-doc-exporter/0.1.0"}
        if auth:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _url(self, path: str, *, query: Optional[JsonObject] = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            url = f"{url}?{urllib.parse.urlencode(clean_query)}"
        return url

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> FeishuAPIError:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return FeishuAPIError(f"HTTP {exc.code}: {raw[:500]}", status=exc.code, payload=payload)


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def first_string(values: Iterable[Any]) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None
